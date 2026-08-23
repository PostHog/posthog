import { describe, expect, it, vi } from "vitest";
import type { FetchImplementation } from "./fetcher";
import {
  ContextWikiConflictError,
  ContextWikiLintError,
  ContextWikiUnavailableError,
  PostHogAPIClient,
} from "./posthog-client";

function makeClient(fetch: ReturnType<typeof vi.fn>): PostHogAPIClient {
  return new PostHogAPIClient(
    "https://app.posthog.test",
    async () => "token",
    async () => "token",
    42,
    { fetch: fetch as unknown as FetchImplementation },
  );
}

const PAGE_INPUT = {
  path: "projects/12/spaces/growth.md",
  content: "# Growth\n",
  baseHead: "abc123",
};

describe("context wiki client", () => {
  it("resolves a channel wiki page without deriving its path from the channel name", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ path: "projects/12/spaces/growth-renamed.md" }),
        {
          status: 200,
        },
      ),
    );

    await expect(
      makeClient(fetch).getChannelContextWikiPage("channel-id"),
    ).resolves.toEqual({ path: "projects/12/spaces/growth-renamed.md" });
  });

  it("returns null when a channel has no wiki page", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
    await expect(
      makeClient(fetch).getChannelContextWikiPage("channel-id"),
    ).resolves.toBeNull();
  });

  it("returns null from getContextWikiTree when the wiki is not enabled", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
    await expect(makeClient(fetch).getContextWikiTree()).resolves.toBeNull();
  });

  it("maps a 403 tree read to ContextWikiUnavailableError with the server detail", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "Organization has private projects" }),
        {
          status: 403,
        },
      ),
    );
    await expect(makeClient(fetch).getContextWikiTree()).rejects.toThrow(
      ContextWikiUnavailableError,
    );
  });

  it("sends base_head on page writes and returns the new head", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ head_sha: "def456" }), { status: 200 }),
      );
    await expect(
      makeClient(fetch).putContextWikiPage(PAGE_INPUT),
    ).resolves.toEqual({ head_sha: "def456" });
    const request = fetch.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(request.body as string)).toEqual({
      path: "projects/12/spaces/growth.md",
      content: "# Growth\n",
      base_head: "abc123",
    });
  });

  it("maps a stale-head 409 to ContextWikiConflictError carrying the current head", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ current_head: "fff999" }), {
        status: 409,
      }),
    );
    const error = await makeClient(fetch)
      .putContextWikiPage(PAGE_INPUT)
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ContextWikiConflictError);
    expect((error as ContextWikiConflictError).currentHead).toBe("fff999");
  });

  it("maps a lint 400 to ContextWikiLintError with the violation list", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "The change violates the wiki structure.",
          errors: ["AGENTS.md must keep its heading"],
        }),
        { status: 400 },
      ),
    );
    const error = await makeClient(fetch)
      .putContextWikiPage(PAGE_INPUT)
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ContextWikiLintError);
    expect((error as ContextWikiLintError).errors).toEqual([
      "AGENTS.md must keep its heading",
    ]);
  });
});
