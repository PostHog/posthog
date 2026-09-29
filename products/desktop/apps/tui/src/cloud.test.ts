import { describe, expect, it, vi } from "vitest";
import { authenticatedFetch } from "./cloud";

describe("authenticatedFetch", () => {
  it("refreshes the token once after a 401 and retries with the new one", async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response("ok"));
    const auth = {
      getAccessToken: vi.fn(async () => "old"),
      refreshAccessToken: vi.fn(async () => "new"),
    };

    const response = await authenticatedFetch(auth, fetch)(
      "https://us.posthog.com/x",
      { method: "POST" },
    );

    expect(await response.text()).toBe("ok");
    const tokens = fetch.mock.calls.map(([, init]) =>
      new Headers(init?.headers).get("Authorization"),
    );
    expect(tokens).toEqual(["Bearer old", "Bearer new"]);
    expect(fetch.mock.calls[1][1]?.method).toBe("POST");
  });
});
