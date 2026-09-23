import { describe, expect, it, vi } from "vitest";
import { PostHogAPIClient } from "./posthog-client";

describe("routing API", () => {
  it("previews without applying, then submits the reviewed batch ID", async () => {
    const fetch = vi.fn().mockImplementation(
      async () =>
        new Response(JSON.stringify({ id: "batch-1", status: "preview" }), {
          status: 200,
        }),
    );
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "fake-token",
      async () => "fake-token",
      42,
      { fetch },
    );
    await client.previewRoutingDomain({ domain_id: "domain-1" });
    expect(fetch).toHaveBeenCalledOnce();
    expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(
      "/api/projects/42/signals/routing_preferences/preview/",
    );
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      domain_id: "domain-1",
    });
    await client.applyRoutingBatch("batch-1");
    expect(new URL(fetch.mock.calls[1][0]).pathname).toBe(
      "/api/projects/42/signals/routing_batches/batch-1/apply/",
    );
  });

  it("keeps For you on the server ownership filter, including work already owned", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ results: [], count: 0 }), {
        status: 200,
      }),
    );
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "fake-token",
      async () => "fake-token",
      42,
      { fetch },
    );
    await client.getSignalReports({ scope: "for_me" });
    expect(new URL(fetch.mock.calls[0][0]).searchParams.get("scope")).toBe(
      "for_me",
    );
    expect(
      new URL(fetch.mock.calls[0][0]).searchParams.has("suggested_reviewers"),
    ).toBe(false);
  });
});
