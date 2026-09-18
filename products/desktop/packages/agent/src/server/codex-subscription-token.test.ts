import { describe, expect, it, vi } from "vitest";
import type { CodexSubscriptionAccessGrant } from "../posthog-api";
import {
  CODEX_TOKEN_FORCE_COOLDOWN_MS,
  CODEX_TOKEN_REFRESH_MARGIN_MS,
  CodexSubscriptionTokenClient,
} from "./codex-subscription-token";

const START = Date.parse("2030-01-01T00:00:00Z");
const HOUR_MS = 60 * 60_000;

function grant(
  accessToken: string,
  expiresAt: number,
): CodexSubscriptionAccessGrant {
  return {
    access_token: accessToken,
    account_id: "acct-1",
    plan_type: "plus",
    expires_at: new Date(expiresAt).toISOString(),
  };
}

function createClient(now: { value: number }) {
  const requestCodexSubscriptionToken = vi.fn();
  const client = new CodexSubscriptionTokenClient({
    posthogAPI: { requestCodexSubscriptionToken },
    taskId: "task-1",
    runId: "run-1",
    runToken: "run-token",
    now: () => now.value,
  });
  return { client, requestCodexSubscriptionToken };
}

describe("CodexSubscriptionTokenClient", () => {
  it("maps the grant for codex and reuses it until the refresh margin", async () => {
    const now = { value: START };
    const { client, requestCodexSubscriptionToken } = createClient(now);
    requestCodexSubscriptionToken.mockResolvedValueOnce(
      grant("access-1", START + HOUR_MS),
    );

    await expect(client.get()).resolves.toEqual({
      accessToken: "access-1",
      chatgptAccountId: "acct-1",
      chatgptPlanType: "plus",
    });
    expect(requestCodexSubscriptionToken).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      "run-token",
      false,
      expect.any(Number),
    );

    now.value = START + HOUR_MS - CODEX_TOKEN_REFRESH_MARGIN_MS - 1;
    await client.get();
    expect(requestCodexSubscriptionToken).toHaveBeenCalledTimes(1);

    requestCodexSubscriptionToken.mockResolvedValueOnce(
      grant("access-2", START + 2 * HOUR_MS),
    );
    now.value = START + HOUR_MS - CODEX_TOKEN_REFRESH_MARGIN_MS;
    await expect(client.get()).resolves.toMatchObject({
      accessToken: "access-2",
    });
    expect(requestCodexSubscriptionToken).toHaveBeenCalledTimes(2);
  });

  it("forces a new token when codex rejects one, but not twice in a row", async () => {
    const now = { value: START };
    const { client, requestCodexSubscriptionToken } = createClient(now);
    requestCodexSubscriptionToken
      .mockResolvedValueOnce(grant("access-1", START + HOUR_MS))
      .mockResolvedValueOnce(grant("access-2", START + 2 * HOUR_MS));
    await client.get();

    now.value = START + CODEX_TOKEN_FORCE_COOLDOWN_MS;
    await expect(client.refresh()).resolves.toMatchObject({
      accessToken: "access-2",
    });
    expect(requestCodexSubscriptionToken).toHaveBeenLastCalledWith(
      "task-1",
      "run-1",
      "run-token",
      true,
      expect.any(Number),
    );

    await expect(client.refresh()).resolves.toMatchObject({
      accessToken: "access-2",
    });
    expect(requestCodexSubscriptionToken).toHaveBeenCalledTimes(2);
  });

  it("shares one in-flight request between concurrent callers", async () => {
    const now = { value: START };
    const { client, requestCodexSubscriptionToken } = createClient(now);
    let release: (value: CodexSubscriptionAccessGrant) => void = () => {};
    requestCodexSubscriptionToken.mockReturnValueOnce(
      new Promise<CodexSubscriptionAccessGrant>((resolve) => {
        release = resolve;
      }),
    );

    const first = client.get();
    const second = client.refresh();
    release(grant("access-1", START + HOUR_MS));

    await expect(Promise.all([first, second])).resolves.toEqual([
      expect.objectContaining({ accessToken: "access-1" }),
      expect.objectContaining({ accessToken: "access-1" }),
    ]);
    expect(requestCodexSubscriptionToken).toHaveBeenCalledTimes(1);
  });
});
