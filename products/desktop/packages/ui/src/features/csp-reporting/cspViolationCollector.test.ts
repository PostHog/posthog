import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { startCspViolationCollector } from "./cspViolationCollector";
import { CSP_VIOLATION_NOTIFICATION } from "./identifiers";

function violation(blockedURL: string, directive = "style-src-elem") {
  return {
    jsonrpc: "2.0",
    method: CSP_VIOLATION_NOTIFICATION,
    params: {
      report: {
        type: "csp-violation",
        url: "mcp-sandbox://proxy/",
        body: {
          documentURL: "mcp-sandbox://proxy/",
          blockedURL,
          effectiveDirective: directive,
          disposition: "enforce",
        },
      },
    },
  };
}

function post(data: unknown) {
  window.dispatchEvent(new MessageEvent("message", { data }));
}

let dispose: (() => void) | null = null;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  dispose?.();
  dispose = null;
  vi.useRealTimers();
});

describe("startCspViolationCollector", () => {
  it("batches the violations that arrive within one flush window", () => {
    const send = vi.fn();
    dispose = startCspViolationCollector({ send, flushDelayMs: 500 });

    post(violation("https://mcp.us.posthog.com/ui-apps/x/styles.css"));
    post(
      violation(
        "https://mcp.us.posthog.com/ui-apps/x/main.js",
        "script-src-elem",
      ),
    );
    expect(send).not.toHaveBeenCalled();

    vi.advanceTimersByTime(500);

    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0][0]).toHaveLength(2);
    expect(send.mock.calls[0][0][0].body.blockedURL).toBe(
      "https://mcp.us.posthog.com/ui-apps/x/styles.css",
    );
  });

  it("sends a repeated violation only once", () => {
    const send = vi.fn();
    dispose = startCspViolationCollector({ send, flushDelayMs: 500 });

    post(violation("https://mcp.us.posthog.com/a.css"));
    post(violation("https://mcp.us.posthog.com/a.css"));
    vi.advanceTimersByTime(500);

    expect(send.mock.calls[0][0]).toHaveLength(1);
  });

  it("stops collecting once the distinct-report cap is reached", () => {
    const send = vi.fn();
    dispose = startCspViolationCollector({
      send,
      flushDelayMs: 500,
      maxDistinctReports: 2,
    });

    post(violation("https://mcp.us.posthog.com/1.css"));
    post(violation("https://mcp.us.posthog.com/2.css"));
    post(violation("https://mcp.us.posthog.com/3.css"));
    vi.advanceTimersByTime(500);

    expect(send.mock.calls[0][0]).toHaveLength(2);
  });

  it.each([
    ["an unrelated method", { method: "ui/notifications/sandbox-proxy-ready" }],
    ["a missing report", { method: CSP_VIOLATION_NOTIFICATION, params: {} }],
    ["a non-object payload", "hello"],
  ])("ignores %s", (_name, data) => {
    const send = vi.fn();
    dispose = startCspViolationCollector({ send, flushDelayMs: 500 });

    post(data);
    vi.advanceTimersByTime(500);

    expect(send).not.toHaveBeenCalled();
  });

  it("flushes what it holds when disposed", () => {
    const send = vi.fn();
    const stop = startCspViolationCollector({ send, flushDelayMs: 500 });

    post(violation("https://mcp.us.posthog.com/a.css"));
    stop();

    expect(send).toHaveBeenCalledTimes(1);
  });

  it("stops listening after disposal", () => {
    const send = vi.fn();
    const stop = startCspViolationCollector({ send, flushDelayMs: 500 });
    stop();

    post(violation("https://mcp.us.posthog.com/a.css"));
    vi.advanceTimersByTime(500);

    expect(send).not.toHaveBeenCalled();
  });
});
