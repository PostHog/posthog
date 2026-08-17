import type {
  ExtensionAPI,
  ExtensionContext,
  ToolResultEvent,
} from "@earendil-works/pi-coding-agent";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createPiEnrichmentExtension } from "./enrichment-extension";

type ToolResultPatch = { content?: ToolResultEvent["content"] };
type ToolResultHandler = (
  event: ToolResultEvent,
  ctx: ExtensionContext,
) => Promise<ToolResultPatch | undefined> | ToolResultPatch | undefined;

describe("createPiEnrichmentExtension", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("adds live PostHog metadata to Pi read results", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input);
        const data = url.includes("event_definitions")
          ? {
              results: [
                {
                  id: "event-1",
                  name: "checkout",
                  tags: [],
                  last_seen_at: "2026-01-01T00:00:00Z",
                  verified: true,
                },
              ],
            }
          : {
              results: [["checkout", 120, 40, "2026-01-01T00:00:00Z"]],
            };
        return new Response(JSON.stringify(data), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    let handler: ToolResultHandler | undefined;
    const extension = createPiEnrichmentExtension({
      apiUrl: "https://us.posthog.com",
      projectId: 1,
      apiKey: "token",
    });
    await extension.factory({
      on: (event: string, registeredHandler: ToolResultHandler) => {
        if (event === "tool_result") {
          handler = registeredHandler;
        }
      },
    } as unknown as ExtensionAPI);

    const result = await handler?.(
      {
        type: "tool_result",
        toolCallId: "read-1",
        toolName: "read",
        input: { path: "/tmp/example.ts" },
        content: [{ type: "text", text: 'posthog.capture("checkout");' }],
        details: undefined,
        isError: false,
      },
      { cwd: "/tmp" } as ExtensionContext,
    );

    expect(result?.content).toEqual([
      {
        type: "text",
        text: expect.stringContaining(
          '[PostHog] Event: "checkout" — (verified) — 120 events — 40 users',
        ),
      },
    ]);
  });
});
