import type { McpUiResource } from "@posthog/core/mcp-apps/schemas";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { renderHook } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAppBridge } from "./useAppBridge";

const { bridgeInstances, createMockAppBridge, connectGate } = vi.hoisted(() => {
  // When gated, connect stays pending until the test releases it, so a test
  // can run a teardown while a connect is in flight.
  const connectGate = {
    enabled: false,
    resolvers: [] as Array<() => void>,
    enable() {
      this.enabled = true;
    },
    release() {
      this.enabled = false;
      for (const resolve of this.resolvers.splice(0)) resolve();
    },
  };
  class MockAppBridge {
    oninitialized: (() => void) | null = null;
    sendToolResult = vi.fn();
    sendToolInput = vi.fn();
    sendHostContextChange = vi.fn();
    connect = vi.fn().mockImplementation(() => {
      if (!connectGate.enabled) return Promise.resolve();
      return new Promise<void>((resolve) => {
        connectGate.resolvers.push(resolve);
      });
    });
    sendSandboxResourceReady = vi.fn().mockResolvedValue(undefined);
    teardownResource = vi.fn().mockResolvedValue(undefined);
    close = vi.fn().mockResolvedValue(undefined);
  }
  const bridgeInstances: MockAppBridge[] = [];
  function createMockAppBridge() {
    const instance = new MockAppBridge();
    bridgeInstances.push(instance);
    return instance;
  }
  return { bridgeInstances, createMockAppBridge, connectGate };
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
  connectGate.release();
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

    // Not yet initialized, so this only reaches `pendingRef`.
    act(() => {
      result.current.sendResultOnce("tc-1", { content: [] });
    });
    expect(firstBridge.sendToolResult).not.toHaveBeenCalled();

    rerender(baseArgs({ uiResource: makeResource("ui://posthog/other.html") }));

    await act(async () => {
      await dispatchProxyReady();
    });
    expect(bridgeInstances).toHaveLength(2);
    const secondBridge = bridgeInstances[1];

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

  it("drops a bridge whose connect finishes after a teardown (regression)", async () => {
    connectGate.enable();
    const onPhaseChange = vi.fn();
    const { rerender } = renderHook((props) => useAppBridge(props), {
      initialProps: baseArgs({ onPhaseChange }),
    });

    await act(async () => {
      // Do not await the listener: with the gate on, it parks at connect.
      void latestMessageListener?.({
        source: fakeIframeEl.contentWindow,
        data: { method: "ui/notifications/sandbox-proxy-ready" },
      } as MessageEvent);
      await Promise.resolve();
    });
    expect(bridgeInstances).toHaveLength(1);
    const staleBridge = bridgeInstances[0];

    // The resource changes while connect is still pending, so the effect
    // that started this bridge tears down.
    rerender(
      baseArgs({
        onPhaseChange,
        uiResource: makeResource("ui://posthog/other.html"),
      }),
    );

    await act(async () => {
      connectGate.release();
    });

    expect(staleBridge.sendSandboxResourceReady).not.toHaveBeenCalled();
    expect(staleBridge.close).toHaveBeenCalled();
    expect(onPhaseChange).not.toHaveBeenCalledWith("resource-sent");
  });

  it("does not double-deliver when a result was already queued before the app initializes", async () => {
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
