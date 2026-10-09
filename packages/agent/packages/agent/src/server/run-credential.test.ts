import { describe, expect, it, vi } from "vitest";
import { RunCredentialError } from "../posthog-api";
import {
  RunCredentialClient,
  runCredentialFailureMessage,
} from "./run-credential";

function createClient() {
  const requestStoredRunCredential = vi.fn();
  const info = vi.fn();
  const client = new RunCredentialClient({
    posthogAPI: { requestStoredRunCredential },
    taskId: "task-1",
    runId: "run-1",
    runToken: "run-token",
    logger: { info } as never,
  });
  return { client, requestStoredRunCredential, info };
}

describe("RunCredentialClient", () => {
  it("fetches a credential once with the run token and never logs the secret", async () => {
    const { client, requestStoredRunCredential, info } = createClient();
    requestStoredRunCredential.mockResolvedValue("sk-ant-oat01-fake");

    const [first, second] = await Promise.all([
      client.get("claude_subscription"),
      client.get("claude_subscription"),
    ]);
    const third = await client.get("claude_subscription");

    expect([first, second, third]).toEqual([
      "sk-ant-oat01-fake",
      "sk-ant-oat01-fake",
      "sk-ant-oat01-fake",
    ]);
    expect(requestStoredRunCredential).toHaveBeenCalledTimes(1);
    expect(requestStoredRunCredential).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      "run-token",
      "claude_subscription",
      expect.any(Number),
    );
    expect(JSON.stringify(info.mock.calls)).not.toContain("sk-ant-oat01-fake");
  });

  it("asks again after a failed request", async () => {
    const { client, requestStoredRunCredential } = createClient();
    requestStoredRunCredential
      .mockRejectedValueOnce(
        new RunCredentialError(
          "claude_subscription",
          "request_failed",
          500,
          "x",
        ),
      )
      .mockResolvedValueOnce("sk-ant-oat01-fake");

    await expect(client.get("claude_subscription")).rejects.toMatchObject({
      code: "request_failed",
    });
    await expect(client.get("claude_subscription")).resolves.toBe(
      "sk-ant-oat01-fake",
    );
  });

  it.each([
    [
      "claude_subscription",
      "credential_missing",
      "Add your Claude subscription in Cloud agents settings, then start the run again.",
    ],
    [
      "claude_subscription",
      "forbidden",
      "This run could not get your Claude subscription from PostHog. Start the run again.",
    ],
  ] as const)(
    "explains a %s request that failed with %s",
    (credential, code, message) => {
      expect(
        runCredentialFailureMessage(
          credential,
          new RunCredentialError(credential, code, 404, "x"),
        ),
      ).toBe(message);
    },
  );
});
