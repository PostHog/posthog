import type { AuthState } from "@posthog/core/auth/schemas";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getAuthenticatedClient } from "./authClientImperative";
import { getCachedAuthState } from "./authQueries";
import { ANONYMOUS_AUTH_STATE } from "./store";

vi.mock("./authQueries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./authQueries")>()),
  getCachedAuthState: vi.fn(),
}));

describe("getAuthenticatedClient", () => {
  beforeEach(() => {
    vi.mocked(getCachedAuthState).mockReset();
  });

  it("uses this window's project when creating an imperative client", async () => {
    vi.mocked(getCachedAuthState).mockReturnValue({
      ...ANONYMOUS_AUTH_STATE,
      status: "authenticated",
      bootstrapComplete: true,
      cloudRegion: "us",
      currentProjectId: 41,
      sessionType: "persistent",
    } satisfies AuthState);

    const client = await getAuthenticatedClient();
    const projectClient = client as unknown as {
      getTeamId(): Promise<number | undefined>;
    };

    await expect(projectClient.getTeamId()).resolves.toBe(41);
  });
});
