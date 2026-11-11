import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CredentialRelay } from "./credential-relay";

describe("CredentialRelay", () => {
  let events: Record<string, unknown>[];

  beforeEach(() => {
    vi.useFakeTimers();
    events = [];
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function makeRelay(timeoutMs?: number): CredentialRelay {
    return new CredentialRelay({
      emitEvent: (event) => events.push(event),
      ...(timeoutMs !== undefined ? { timeoutMs } : {}),
    });
  }

  it("resolves with the token when the matching response arrives", async () => {
    const relay = makeRelay();
    const tokenPromise = relay.request("claude_subscription_token");

    expect(events).toHaveLength(1);
    const event = events[0] as {
      type: string;
      requestId: string;
      credential: string;
    };
    expect(event.type).toBe("credential_request");
    expect(event.credential).toBe("claude_subscription_token");

    relay.resolve({
      requestId: event.requestId,
      token: "sk-ant-oat01-fake-test-token",
    });
    await expect(tokenPromise).resolves.toBe("sk-ant-oat01-fake-test-token");
    expect(
      relay.resolve({ requestId: event.requestId, token: "another-token" }),
    ).toBe(true);
  });

  it("rejects with a safe message when the response carries an error", async () => {
    const relay = makeRelay();
    const tokenPromise = relay.request("claude_subscription_token");
    const { requestId } = events[0] as { requestId: string };

    relay.resolve({ requestId, error: "sensitive-untrusted-error" });
    await expect(tokenPromise).rejects.toThrow(
      "PostHog Desktop could not provide the Claude token.",
    );
  });

  it("rejects on timeout", async () => {
    const relay = makeRelay(120_000);
    const tokenPromise = relay.request("claude_subscription_token");

    const assertion = expect(tokenPromise).rejects.toThrow(
      "timed out waiting for PostHog Desktop",
    );
    await vi.advanceTimersByTimeAsync(120_000);
    await assertion;
  });

  it("ignores a response with an unknown requestId", async () => {
    const relay = makeRelay();
    const tokenPromise = relay.request("claude_subscription_token");
    const { requestId } = events[0] as { requestId: string };

    const resolved = relay.resolve({
      requestId: "not-a-pending-request",
      token: "sk-ant-oat01-fake-test-token",
    });

    expect(resolved).toBe(false);
    relay.resolve({ requestId, token: "sk-ant-oat01-fake-test-token" });
    await expect(tokenPromise).resolves.toBe("sk-ant-oat01-fake-test-token");
  });

  it("emits no event containing the token", async () => {
    const relay = makeRelay();
    const tokenPromise = relay.request("claude_subscription_token");
    const { requestId } = events[0] as { requestId: string };

    relay.resolve({ requestId, token: "sk-ant-oat01-fake-test-token" });
    await tokenPromise;

    const serialized = JSON.stringify(events);
    expect(serialized).not.toContain("sk-ant-oat01-fake-test-token");
  });

  it("rejects pending and future requests on shutdown", async () => {
    const relay = makeRelay();
    const pending = relay.request("claude_subscription_token");
    relay.stop();
    await expect(pending).rejects.toThrow("Session is shutting down.");
    await expect(relay.request("claude_subscription_token")).rejects.toThrow(
      "Session is shutting down.",
    );
    expect(vi.getTimerCount()).toBe(0);
  });
});
