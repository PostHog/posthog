import type { UserCodexIntegration } from "@posthog/api-client/posthog-client";
import { connectCodexCloudAccount } from "@posthog/ui/features/settings/connectCodexCloudAccount";
import { describe, expect, it, vi } from "vitest";

const tokens = {
  access_token: "access-example",
  refresh_token: "refresh-example",
  id_token: null,
};

const connected: UserCodexIntegration = {
  status: "connected",
  plan_type: "plus",
  email: "user@example.com",
  connected_at: "2026-01-01T00:00:00Z",
};

describe("connectCodexCloudAccount", () => {
  it("removes the local login file only after PostHog accepted the tokens", async () => {
    const client = {
      connectCodexUserIntegration: vi.fn().mockResolvedValue(connected),
    };
    const authFile = {
      read: vi.fn().mockResolvedValue(tokens),
      remove: vi.fn().mockResolvedValue(undefined),
    };

    await expect(connectCodexCloudAccount(client, authFile)).resolves.toEqual(
      connected,
    );

    expect(client.connectCodexUserIntegration).toHaveBeenCalledWith(tokens);
    expect(authFile.remove).toHaveBeenCalledTimes(1);
  });

  it("keeps the local login file when PostHog rejects the tokens", async () => {
    const client = {
      connectCodexUserIntegration: vi
        .fn()
        .mockRejectedValue(new Error("OpenAI rejected the login")),
    };
    const authFile = {
      read: vi.fn().mockResolvedValue(tokens),
      remove: vi.fn().mockResolvedValue(undefined),
    };

    await expect(connectCodexCloudAccount(client, authFile)).rejects.toThrow(
      "OpenAI rejected the login",
    );

    expect(authFile.remove).not.toHaveBeenCalled();
  });
});
