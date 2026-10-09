import { describe, expect, it, vi } from "vitest";
import { authenticatedFetch, cloudEngineFor } from "./cloud";

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

describe("cloudEngineFor", () => {
  it("keeps one engine per account across reloads, reading tokens from the latest sign-in", async () => {
    const tokens = (access: string) => ({
      getAccessToken: async () => access,
      refreshAccessToken: async () => access,
    });
    let seen: { getAccessToken: () => Promise<string> } | undefined;
    const build = vi.fn((source: typeof seen) => {
      seen = source;
      return { id: Math.random() };
    });
    const first = cloudEngineFor("us me", tokens("old"), build);
    // A reload signs in again from the saved session: same account, fresh tokens, same engine.
    const again = cloudEngineFor("us me", tokens("new"), build);
    const other = cloudEngineFor("eu me", tokens("eu"), build);
    expect(again).toBe(first);
    expect(other).not.toBe(first);
    expect(build).toHaveBeenCalledTimes(2);
    expect(seen).toBeDefined();
    await expect(
      cloudEngineFor("us me", tokens("newer"), build) === first
        ? (
            build.mock.calls[0][0] as { getAccessToken: () => Promise<string> }
          ).getAccessToken()
        : Promise.resolve("wrong engine"),
    ).resolves.toBe("newer");
  });
});
