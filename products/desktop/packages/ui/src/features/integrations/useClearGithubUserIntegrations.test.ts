import { describe, expect, it, vi } from "vitest";
import { clearGithubUserIntegrations } from "./useClearGithubUserIntegrations";

describe("clearGithubUserIntegrations", () => {
  it("disconnects every personal GitHub installation", async () => {
    const disconnectGithubUserIntegration = vi
      .fn()
      .mockResolvedValue(undefined);
    const client = {
      getGithubUserIntegrations: vi
        .fn()
        .mockResolvedValue([
          { installation_id: "installation-1" },
          { installation_id: "installation-2" },
        ]),
      disconnectGithubUserIntegration,
    };

    await expect(clearGithubUserIntegrations(client)).resolves.toBe(2);
    expect(disconnectGithubUserIntegration).toHaveBeenCalledTimes(2);
    expect(disconnectGithubUserIntegration).toHaveBeenCalledWith(
      "installation-1",
    );
    expect(disconnectGithubUserIntegration).toHaveBeenCalledWith(
      "installation-2",
    );
  });

  it("does nothing when no personal GitHub installation exists", async () => {
    const disconnectGithubUserIntegration = vi.fn();
    const client = {
      getGithubUserIntegrations: vi.fn().mockResolvedValue([]),
      disconnectGithubUserIntegration,
    };

    await expect(clearGithubUserIntegrations(client)).resolves.toBe(0);
    expect(disconnectGithubUserIntegration).not.toHaveBeenCalled();
  });
});
