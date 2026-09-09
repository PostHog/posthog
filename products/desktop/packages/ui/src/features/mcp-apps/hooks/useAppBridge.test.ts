import type { McpUiResource } from "@posthog/core/mcp-apps/schemas";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { renderHook } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAppBridge } from "./useAppBridge";

const { bridgeInstances, createMockAppBridge } = vi.hoisted(() => {
  class MockAppBridge {
    oninitialized: (() => void) | null = null;
    sendToolResult = vi.fn();
    sendToolInput = vi.fn();
    sendHostContextChange = vi.fn();
    connect = vi.fn().mockResolvedValue(undefined);
    sendSandboxResourceReady = vi.fn().mockResolvedValue(undefined);
    teardownResource = vi.fn().mockResolvedValue(undefined);
    close = vi.fn().mockResolvedValue(undefined);
  }
  const bridgeInstances: MockAppBridge[] = [];
  // Named function, not an inline arrow — `new AppBridge()` needs a real
  // constructor, and an autofixer would otherwise rewrite an inline one
  // back into a non-constructible arrow function.
  function createMockAppBridge() {
    const instance = new MockAppBridge();
    bridgeInstances.push(instance);
    return instance;
  }
  return { bridgeInstances, createMockAppBridge };
});

vi.mock("@modelcontextprotocol/ext-apps/app-bridge", () => ({
  AppBridge: vi.fn().mockImplementation(createMockAppBridge),
  PostMessageTransport: vi.fn(),
}));

vi.mock("@posthog/ui/router/useAppView", () => ({
  getAppViewSnapshot: () => ({ type: "default" }),
}));

vi.mock("../../message-editor/draftStore", () => ({
  useDraftStore: {
    getState: () => ({
      actions: { setPendingContent: vi.fn(), requestFocus: vi.fn() },
    }),
  },
}));

// The hook waits for a real `message` event from the proxy iframe before it
// builds a bridge. jsdom won't let a test forge `MessageEvent.source` to
// match `iframe.contentWindow`, so this captures the listener the hook's
// effect registers and invokes it directly with a fake event.
let latestMessageListener: ((event: MessageEvent) => void) | undefined;

beforeEach(() => {
  latestMessageListener = undefined;
  const realAddEventListener = window.addEventListener.bind(window);
  vi.spyOn(window, "addEventListener").mockImplementation(
    (type, listener, options) => {
      if (type === "message") {
        latestMessageListener = listener as (event: MessageEvent) => void;
      }
      return realAddEventListener(
        type,
        listener as EventListenerOrEventListenerObject,
        options,
      );
    },
  );
});

afterEach(() => {
  bridgeInstances.length = 0;
  vi.restoreAllMocks();
});

function makeToolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    toolCallId: "tc-1",
    title: "posthog",
    kind: "other",
    status: "completed",
    rawInput: { foo: "bar" },
    ...overrides,
  };
}

function makeResource(uri: string): McpUiResource {
  return { uri, mimeType: "text/html", html: "<div/>", serverName: "posthog" };
}

const fakeIframeEl = {
  contentWindow: { name: "sandbox-proxy" },
} as unknown as HTMLIFrameElement;

async function dispatchProxyReady() {
  await latestMessageListener?.({
    source: fakeIframeEl.contentWindow,
    data: { method: "ui/notifications/sandbox-proxy-ready" },
  } as MessageEvent);
}

function baseArgs(overrides: Record<string, unknown> = {}) {
  return {
    iframeEl: fakeIframeEl,
    uiResource: makeResource("ui://posthog/query-results.html"),
    serverName: "posthog",
    toolName: "exec",
    toolDefinition: null,
    toolCall: makeToolCall(),
    isDarkMode: false,
    displayMode: "inline" as const,
    containerWidth: 640,
    onPhaseChange: vi.fn(),
    onSizeChange: vi.fn(),
    onDisplayModeChange: vi.fn(),
    proxyToolCall: vi.fn(),
    proxyResourceRead: vi.fn(),
    openLink: vi.fn(),
    ...overrides,
  };
}

describe("useAppBridge", () => {
  it("redelivers a result queued before teardown once a new bridge initializes", async () => {
    const { result, rerender } = renderHook((props) => useAppBridge(props), {
      initialProps: baseArgs(),
    });

    await act(async () => {
      await dispatchProxyReady();
    });
    expect(bridgeInstances).toHaveLength(1);
    const firstBridge = bridgeInstances[0];

    // Queued before the app's own handshake completes — not yet initialized,
    // so this only reaches `pendingRef`, not `sendToolResult`.
    act(() => {
      result.current.sendResultOnce("tc-1", { content: [] });
    });
    expect(firstBridge.sendToolResult).not.toHaveBeenCalled();

    // A `uiResource` identity change (e.g. an MCP discovery refetch) tears
    // the bridge down before it ever flushed the queued result.
    rerender(baseArgs({ uiResource: makeResource("ui://posthog/other.html") }));

    await act(async () => {
      await dispatchProxyReady();
    });
    expect(bridgeInstances).toHaveLength(2);
    const secondBridge = bridgeInstances[1];

    // The retry (the exec-replay effect, or `oninitialized`'s own remount
    // catch-up) must not be blocked by a flag that survived the teardown.
    act(() => {
      result.current.sendResultOnce("tc-1", { content: [] });
    });
    act(() => {
      secondBridge.oninitialized?.();
    });

    expect(secondBridge.sendToolResult).toHaveBeenCalledTimes(1);
    expect(firstBridge.sendToolResult).not.toHaveBeenCalled();
  });

  it("delivers a result immediately once, ignoring a duplicate call for the same toolCallId", async () => {
    const { result } = renderHook((props) => useAppBridge(props), {
      initialProps: baseArgs(),
    });

    await act(async () => {
      await dispatchProxyReady();
    });
    const bridge = bridgeInstances[0];

    act(() => {
      bridge.oninitialized?.();
    });

    act(() => {
      result.current.sendResultOnce("tc-1", { content: [] });
      result.current.sendResultOnce("tc-1", { content: [] });
    });

    expect(bridge.sendToolResult).toHaveBeenCalledTimes(1);
  });

  it("sends an already-completed tool call's result once the app initializes", async () => {
    // A row that only ever renders once its result is known (e.g. a chart pulled out of a
    // collapsed tool-call group) mounts with `rawOutput` already set on the very first render —
    // nothing else has queued a result yet when the app finishes its own handshake.
    renderHook((props) => useAppBridge(props), {
      initialProps: baseArgs({
        toolCall: makeToolCall({ rawOutput: { content: [] } }),
      }),
    });

    await act(async () => {
      await dispatchProxyReady();
    });
    const bridge = bridgeInstances[0];

    act(() => {
      bridge.oninitialized?.();
    });

    expect(bridge.sendToolResult).toHaveBeenCalledTimes(1);
  });

  it("does not double-deliver when a result was already queued before the app initializes", async () => {
    // Reproduces the bug: the exec-replay effect queues the result as soon as it mounts, then
    // `oninitialized`'s own remount catch-up sent it again with no dedup against that queue.
    const { result } = renderHook((props) => useAppBridge(props), {
      initialProps: baseArgs({
        toolCall: makeToolCall({ rawOutput: { content: [] } }),
      }),
    });

    await act(async () => {
      await dispatchProxyReady();
    });
    const bridge = bridgeInstances[0];

    act(() => {
      result.current.sendResultOnce("tc-1", { content: [] });
    });
    expect(bridge.sendToolResult).not.toHaveBeenCalled();

    act(() => {
      bridge.oninitialized?.();
    });

    expect(bridge.sendToolResult).toHaveBeenCalledTimes(1);
  });
});
