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
  it.each([
    { method: "list", response: {} },
    { method: "list", response: [{ id: "proposal-1", content: "New text" }] },
    { method: "apply", response: {} },
    { method: "apply", response: { head_sha: 123 } },
  ])(
    "rejects malformed $method responses: $response",
    async ({ method, response }) => {
      const fetch = vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify(response)));
      const client = makeClient(fetch);
      await expect(
        method === "list"
          ? client.getContextWikiProposals()
          : client.applyContextWikiProposal("proposal-1"),
      ).rejects.toThrow();
    },
  );

  it.each([
    { status: 200, response: [] },
    {
      status: 200,
      response: [
        {
          id: "proposal-1",
          task_id: "task-1",
          path: "areas/example.md",
          original_content: "Old text",
          content: "New text",
          base_head: "base-head",
          created_at: "2026-09-11T10:00:00Z",
        },
      ],
    },
    { status: 404, response: null },
  ])(
    "reads proposal responses: $status $response",
    async ({ status, response }) => {
      const fetch = vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify(response), { status }));
      await expect(
        makeClient(fetch).getContextWikiProposals(),
      ).resolves.toEqual(response);
    },
  );

  it("applies the stored suggestion without a replacement body", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ head_sha: "new-head" })),
      );
    await expect(
      makeClient(fetch).applyContextWikiProposal("proposal-1"),
    ).resolves.toEqual({ head_sha: "new-head" });
    expect(String(fetch.mock.calls[0][0])).toContain(
      "/context_layer/proposals/proposal-1/apply/",
    );
    expect(fetch.mock.calls[0][1].body).toBeUndefined();
    expect(fetch.mock.calls[0][1].method).toBe("POST");
  });
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
