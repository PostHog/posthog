import {
  AppBridge,
  type McpUiDisplayMode,
  type McpUiHostCapabilities,
  type McpUiHostContext,
  type McpUiStyles,
  PostMessageTransport,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type {
  CallToolResult,
  ReadResourceResult,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import type { McpUiResource } from "@posthog/core/mcp-apps/schemas";
import { getAppViewSnapshot } from "@posthog/ui/router/useAppView";
import { useCallback, useEffect, useRef } from "react";
import { logger } from "../../../shell/logger";
import { useDraftStore } from "../../message-editor/draftStore";
import type { ToolCall } from "../../sessions/types";
import {
  computeContainerDimensions,
  INLINE_MAX_HEIGHT,
  toCallToolResult,
} from "../utils/mcp-app-host-utils";
import { buildHostStyles } from "../utils/mcp-app-theme";

const log = logger.scope("mcp-app-bridge");

export type Phase =
  | "loading"
  | "proxy-ready"
  | "resource-sent"
  | "initialized"
  | "error";

interface UseAppBridgeArgs {
  iframeEl: HTMLIFrameElement | null;
  uiResource: McpUiResource | null | undefined;
  serverName: string;
  toolName: string;
  toolDefinition?: Tool | null;
  toolCall: ToolCall;
  isDarkMode: boolean;
  displayMode: McpUiDisplayMode;
  containerWidth: number;
  onPhaseChange: (phase: Phase) => void;
  onSizeChange: (height: number) => void;
  onDisplayModeChange: (mode: McpUiDisplayMode) => void;
  proxyToolCall: (args: {
    serverName: string;
    toolName: string;
    args?: Record<string, unknown>;
  }) => Promise<CallToolResult>;
  proxyResourceRead: (args: {
    serverName: string;
    uri: string;
  }) => Promise<ReadResourceResult>;
  openLink: (args: { url: string }) => Promise<void>;
}

interface UseAppBridgeReturn {
  sendWhenReady: (fn: (bridge: AppBridge) => void) => void;
}

const HOST_INFO = { name: "posthog-code", version: "1.0.0" };

const HOST_CAPABILITIES: McpUiHostCapabilities = {
  openLinks: {},
  serverTools: {},
  serverResources: {},
  logging: {},
  message: { text: {} },
  sandbox: {},
};

function buildInitialHostContext(
  isDarkMode: boolean,
  displayMode: McpUiDisplayMode,
  containerWidth: number,
  toolDefinition?: Tool | null,
): McpUiHostContext {
  const hostStyles = buildHostStyles(isDarkMode);

  return {
    theme: isDarkMode ? "dark" : "light",
    styles: {
      variables: hostStyles.variables as McpUiStyles,
      css: hostStyles.css,
    },
    availableDisplayModes: ["inline", "fullscreen"],
    displayMode,
    containerDimensions: computeContainerDimensions(
      displayMode,
      containerWidth,
    ),
    locale: navigator.language,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    userAgent: navigator.userAgent,
    platform: "desktop",
    deviceCapabilities: { touch: false, hover: true },
    safeAreaInsets: { top: 0, right: 0, bottom: 0, left: 0 },
    ...(toolDefinition ? { toolInfo: { tool: toolDefinition } } : {}),
  };
}

/**
 * Manages the host side of the MCP Apps bridge for a single sandboxed iframe.
 *
 * MCP Apps run inside a double-iframe sandbox (proxy → app) and communicate
 * with the host over JSON-RPC postMessage. Rather than hand-rolling that
 * protocol, this hook wraps the official `AppBridge` from
 * `@modelcontextprotocol/ext-apps` which handles the full JSON-RPC transport,
 * handshake, and message validation.
 *
 * The hook owns the entire bridge lifecycle: it waits for the sandbox proxy to
 * signal readiness, creates and connects the bridge, sends the app's HTML
 * resource into the inner iframe, and tears everything down on unmount. It also
 * forwards host context (theme, display mode, container size) to the app
 * whenever those values change.
 *
 * Because the actual MCP server connection lives in the main process (behind
 * tRPC IPC), the bridge's `client` is `null` — tool calls, resource reads,
 * and link opens are routed through tRPC mutations passed in as props.
 *
 * Returns `sendWhenReady`, which buffers calls until the app has finished
 * initializing, then flushes them. Use it to forward tool results and
 * cancellations from tRPC subscriptions without worrying about timing.
 */
export function useAppBridge(args: UseAppBridgeArgs): UseAppBridgeReturn {
  const bridgeRef = useRef<AppBridge | null>(null);
  const initializedRef = useRef(false);
  const pendingRef = useRef<Array<(bridge: AppBridge) => void>>([]);

  // Single mutable ref for latest props — handlers read from this
  const latestRef = useRef(args);
  latestRef.current = args;

  // Stable references for effect dependencies
  const { iframeEl, uiResource } = args;

  // Track previous context values to compute deltas
  const prevContextRef = useRef<{
    isDarkMode: boolean;
    displayMode: McpUiDisplayMode;
    containerWidth: number;
  } | null>(null);

  // Main lifecycle effect
  useEffect(() => {
    if (!iframeEl || !uiResource) {
      log.debug("useAppBridge effect skipped", {
        hasIframeEl: !!iframeEl,
        hasUiResource: !!uiResource,
        serverName: args.serverName,
      });
      return;
    }

    const iframe = iframeEl;
    const resource = uiResource;
    let cleanedUp = false;

    const onProxyReady = async (event: MessageEvent) => {
      if (event.source !== iframe.contentWindow) return;
      if (event.data?.method !== "ui/notifications/sandbox-proxy-ready") return;
      window.removeEventListener("message", onProxyReady);

      if (cleanedUp) return;

      try {
        const latest = latestRef.current;
        const hostContext = buildInitialHostContext(
          latest.isDarkMode,
          latest.displayMode,
          latest.containerWidth,
          latest.toolDefinition,
        );

        const bridge = new AppBridge(null, HOST_INFO, HOST_CAPABILITIES, {
          hostContext,
        });

        // We are NOT listening to every single event coming from the bridge
        // but this can always very easily be extended to listen to more events if needed
        bridge.oncalltool = async (params) =>
          latestRef.current.proxyToolCall({
            serverName: latestRef.current.serverName,
            toolName: params.name,
            args: params.arguments,
          });

        bridge.onreadresource = async (params) =>
          latestRef.current.proxyResourceRead({
            serverName: latestRef.current.serverName,
            uri: params.uri,
          });

        bridge.onopenlink = async (params) => {
          await latestRef.current.openLink({ url: params.url });
          return {};
        };

        // When an MCP App sends a ui/message, pre-fill the chat input
        // for the active task so the user can review before sending.
        bridge.onmessage = async (params) => {
          const textParts = params.content
            .filter(
              (block): block is { type: "text"; text: string } =>
                block.type === "text",
            )
            .map((block) => block.text);

          const message = textParts.join("\n");
          if (message) {
            // Route to the current task's session, or "default" if not on a task
            const view = getAppViewSnapshot();
            const sessionId =
              view.type === "task-detail"
                ? (view.taskId ?? "default")
                : "default";
            const { setPendingContent, requestFocus } =
              useDraftStore.getState().actions;

            setPendingContent(sessionId, {
              segments: [{ type: "text", text: message }],
            });
            requestFocus(sessionId);
          }
          return {};
        };

        // `pip` is not supported at the moment
        bridge.onrequestdisplaymode = async (params) => {
          const requested = params.mode;
          if (["inline", "fullscreen"].includes(requested)) {
            latestRef.current.onDisplayModeChange(requested);
            return { mode: requested };
          }
          return { mode: latestRef.current.displayMode };
        };

        bridge.onsizechange = (params) => {
          if (params.height && typeof params.height === "number") {
            const maxHeight =
              latestRef.current.displayMode === "inline"
                ? INLINE_MAX_HEIGHT
                : 10000;
            latestRef.current.onSizeChange(Math.min(params.height, maxHeight));
          }
        };

        bridge.onloggingmessage = (params) => {
          log.info("Log forwarding", {
            server: latestRef.current.serverName,
            level: params.level,
            data: params.data,
          });
        };

        bridge.oninitialized = () => {
          log.debug("App initialized, phase -> initialized", {
            serverName: latestRef.current.serverName,
          });
          initializedRef.current = true;
          latestRef.current.onPhaseChange("initialized");

          // Send tool input with complete arguments
          const tc = latestRef.current.toolCall;
          if (tc.rawInput) {
            log.debug("Sending tool input to app", {
              serverName: latestRef.current.serverName,
              tc,
              input: { arguments: tc.rawInput },
            });
            bridge.sendToolInput({
              arguments: tc.rawInput as Record<string, unknown>,
            });
          } else {
            log.warn("No rawInput to send to app", {
              serverName: latestRef.current.serverName,
              toolCallId: tc.toolCallId,
            });
          }

          // If the tool already completed (e.g. component remounted after
          // scrolling back into the virtualized list), send the result now
          // since the subscription event was missed.
          if (
            tc.rawOutput &&
            (tc.status === "completed" || tc.status === "failed")
          ) {
            const toolResult = toCallToolResult(tc.rawOutput);
            log.debug("Sending existing tool result to app (remount)", {
              serverName: latestRef.current.serverName,
              toolResult,
            });
            bridge.sendToolResult(toolResult);
          }

          // Flush pending
          log.debug("Flushing pending messages", {
            count: pendingRef.current.length,
          });
          for (const fn of pendingRef.current) {
            fn(bridge);
          }
          pendingRef.current = [];
        };

        // Connect bridge via PostMessageTransport
        const transport = new PostMessageTransport(
          iframe.contentWindow as Window,
          iframe.contentWindow as Window,
        );
        await bridge.connect(transport);
        bridgeRef.current = bridge;

        // Send resource to proxy
        await bridge.sendSandboxResourceReady({
          html: resource.html,
          csp: resource.csp,
          permissions: resource.permissions,
        });

        if (!cleanedUp) {
          log.debug("Resource sent to proxy, phase -> resource-sent", {
            serverName: latestRef.current.serverName,
          });
          latestRef.current.onPhaseChange("resource-sent");
        }
      } catch (err) {
        log.error("Failed to initialize AppBridge", err);
        if (!cleanedUp) {
          latestRef.current.onPhaseChange("error");
        }
      }
    };

    window.addEventListener("message", onProxyReady);

    return () => {
      cleanedUp = true;
      window.removeEventListener("message", onProxyReady);

      if (bridgeRef.current) {
        const b = bridgeRef.current;
        b.teardownResource({}).catch(() => {});
        b.close().catch(() => {});
      }

      bridgeRef.current = null;
      initializedRef.current = false;
      prevContextRef.current = null;
      pendingRef.current = [];
    };
  }, [iframeEl, uiResource, args.serverName]); // Only re-run when iframe element or resource identity changes

  // Host context change effect — sends deltas when theme/displayMode/containerWidth change
  useEffect(() => {
    if (!initializedRef.current || !bridgeRef.current) return;

    const prev = prevContextRef.current;
    prevContextRef.current = {
      isDarkMode: args.isDarkMode,
      displayMode: args.displayMode,
      containerWidth: args.containerWidth,
    };

    // Skip initial (values already in hostContext from constructor)
    if (!prev) return;

    const bridge = bridgeRef.current;
    const delta: Partial<McpUiHostContext> = {};

    if (prev.isDarkMode !== args.isDarkMode) {
      const hostStyles = buildHostStyles(args.isDarkMode);
      delta.theme = args.isDarkMode ? "dark" : "light";
      delta.styles = {
        variables: hostStyles.variables as McpUiStyles,
        css: hostStyles.css,
      };
    }

    if (
      prev.displayMode !== args.displayMode ||
      prev.containerWidth !== args.containerWidth
    ) {
      delta.displayMode = args.displayMode;
      delta.containerDimensions = computeContainerDimensions(
        args.displayMode,
        args.containerWidth,
      );
    }

    if (Object.keys(delta).length > 0) {
      bridge.sendHostContextChange(delta as McpUiHostContext);
    }
  }, [args.isDarkMode, args.displayMode, args.containerWidth]);

  const sendWhenReady = useCallback((fn: (bridge: AppBridge) => void) => {
    if (initializedRef.current && bridgeRef.current) {
      fn(bridgeRef.current);
    } else {
      pendingRef.current.push(fn);
    }
  }, []);

  return { sendWhenReady };
}
