import type {
  ExtensionAPI,
  ExtensionContext,
  ToolResultEvent,
} from "@earendil-works/pi-coding-agent";
import { RICH_OUTPUT_TAGS_PROMPT } from "@posthog/shared/rich-output-prompt";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createPiEnrichmentExtension } from "./enrichment-extension";

type ToolResultPatch = { content?: ToolResultEvent["content"] };
type BeforeAgentStartHandler = (event: { systemPrompt: string }) => {
  systemPrompt: string;
};
type ToolResultHandler = (
  event: ToolResultEvent,
  ctx: ExtensionContext,
) => Promise<ToolResultPatch | undefined> | ToolResultPatch | undefined;

describe("createPiEnrichmentExtension", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([
    [undefined, true],
    ["desktop", true],
    ["signal_report", true],
    ["slack", false],
    ["posthog_ai", false],
  ] as const)(
    "adds surface-specific instructions and live metadata for %s",
    async (interactionOrigin, richOutput) => {
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
      let beforeAgentStartHandler: BeforeAgentStartHandler | undefined;
      const extension = createPiEnrichmentExtension({
        apiUrl: "https://us.posthog.com",
        projectId: 1,
        apiKey: "token",
        interactionOrigin,
      });
      await extension.factory({
        on: (
          event: string,
          registeredHandler: ToolResultHandler | BeforeAgentStartHandler,
        ) => {
          if (event === "tool_result") {
            handler = registeredHandler as ToolResultHandler;
          }
          if (event === "before_agent_start") {
            beforeAgentStartHandler =
              registeredHandler as BeforeAgentStartHandler;
          }
        },
      } as unknown as ExtensionAPI);

      expect(
        beforeAgentStartHandler?.({
          systemPrompt: "Base system prompt",
        }).systemPrompt.includes(RICH_OUTPUT_TAGS_PROMPT),
      ).toBe(richOutput);

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
    },
  );
});
