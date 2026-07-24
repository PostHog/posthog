import {
  AppBridge,
  type McpUiDisplayMode,
  type McpUiHostCapabilities,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type {
  CallToolResult,
  ReadResourceResult,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { useCallback, useEffect, useRef } from "react";
import { Platform } from "react-native";
import type { EdgeInsets } from "react-native-safe-area-context";
import type WebView from "react-native-webview";
import { logger } from "@/lib/logger";
import type { ThemeColors } from "@/lib/theme";
import { buildMcpHostStyles } from "./mcpAppTheme";
import { WebViewTransport } from "./webViewTransport";

const log = logger.scope("mobile-mcp-app-bridge");

export type Phase =
  | "loading"
  | "proxy-ready"
  | "resource-sent"
  | "initialized"
  | "error";

interface UiResource {
  uri: string;
  html: string;
  /** Opaque `McpUiResourceCsp` shape — passed through to AppBridge unchanged. */
  csp?: Record<string, unknown>;
  permissions?: Record<string, Record<string, unknown>>;
}

interface UseMobileAppBridgeArgs {
  webViewRef: { current: WebView | null };
  uiResource: UiResource | null | undefined;
  serverName: string;
  toolDefinition?: Tool | null;
  toolInput?: Record<string, unknown> | null;
  /** Already-completed tool result, used when remounting after the original
   *  result event was missed. */
  existingToolResult?: CallToolResult | null;
  themeColors: ThemeColors;
  isDarkMode: boolean;
  displayMode: McpUiDisplayMode;
  containerWidth: number;
  safeAreaInsets: EdgeInsets;
  onPhaseChange?: (phase: Phase) => void;
  onSizeChange?: (height: number) => void;
  onDisplayModeChange?: (mode: McpUiDisplayMode) => void;
  /** Called when the app requests a tool call via `serverTools`. Round-trip
   *  through the mobile MCP service. */
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
  /** Called when the app sends a `ui/message` (e.g. pre-fill chat input). */
  onAppMessage?: (text: string) => void;
}

interface UseMobileAppBridgeReturn {
  /** Call from the WebView's `onMessage` to feed incoming JSON-RPC. */
  handleWebViewMessage: (payload: string) => void;
  /** Buffer a callback until the app finishes initializing. */
  sendWhenReady: (fn: (bridge: AppBridge) => void) => void;
}

const HOST_INFO = { name: "posthog-code-mobile", version: "1.0.0" };

const HOST_CAPABILITIES: McpUiHostCapabilities = {
  openLinks: {},
  serverTools: {},
  serverResources: {},
  logging: {},
  message: { text: {} },
  sandbox: {},
};

function buildInitialContext(args: UseMobileAppBridgeArgs): McpUiHostContext {
  const hostStyles = buildMcpHostStyles(args.themeColors, args.isDarkMode);
  return {
    theme: args.isDarkMode ? "dark" : "light",
    styles: { variables: hostStyles.variables, css: hostStyles.css },
    availableDisplayModes: ["inline", "fullscreen"],
    displayMode: args.displayMode,
    containerDimensions: {
      width: args.containerWidth,
      // Inline default; the WebView re-sizes after onsizechange fires.
      height: 320,
    },
    locale: "en-US",
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    userAgent: `posthog-code-mobile/${Platform.OS}`,
    platform: "mobile",
    deviceCapabilities: { touch: true, hover: false },
    safeAreaInsets: {
      top: args.safeAreaInsets.top,
      right: args.safeAreaInsets.right,
      bottom: args.safeAreaInsets.bottom,
      left: args.safeAreaInsets.left,
    },
    ...(args.toolDefinition ? { toolInfo: { tool: args.toolDefinition } } : {}),
  };
}

/**
 * Manages a single `AppBridge` lifecycle bound to a WebView. Mirror of
 * desktop's `useAppBridge`, with the iframe `PostMessageTransport` swapped
 * for our `WebViewTransport` and DOM-only host context replaced with
 * React Native equivalents.
 */
export function useMobileAppBridge(
  args: UseMobileAppBridgeArgs,
): UseMobileAppBridgeReturn {
  const bridgeRef = useRef<AppBridge | null>(null);
  const transportRef = useRef<WebViewTransport | null>(null);
  const initializedRef = useRef(false);
  const pendingRef = useRef<Array<(bridge: AppBridge) => void>>([]);

  // Mutable mirror of props so handlers always read latest values.
  const latest = useRef(args);
  latest.current = args;

  // Build/destroy bridge when the UI resource identity changes.
  const { webViewRef, uiResource: uiResourceProp } = args;
  useEffect(() => {
    if (!uiResourceProp) return;
    // Snapshot the resource at effect time so the callback always uses the
    // value we keyed the effect on, even if `args` mutates mid-flight.
    const uiResource = uiResourceProp;

    let cleanedUp = false;

    const setup = async () => {
      try {
        const transport = new WebViewTransport(webViewRef);

        // Wait for the proxy to signal it's ready by capturing the
        // sandbox-proxy-ready notification on the first message.
        const ready = new Promise<void>((resolve, reject) => {
          let resolved = false;
          const previousOnError = transport.onerror;
          const previousOnMessage = transport.onmessage;
          transport.onmessage = (msg) => {
            const m = msg as { method?: string };
            if (
              !resolved &&
              m.method === "ui/notifications/sandbox-proxy-ready"
            ) {
              resolved = true;
              transport.onmessage = previousOnMessage;
              resolve();
              return;
            }
            previousOnMessage?.(msg);
          };
          transport.onerror = (err) => {
            if (!resolved) reject(err);
            previousOnError?.(err);
          };
        });

        await transport.start();
        transportRef.current = transport;

        if (cleanedUp) return;
        await ready;
        if (cleanedUp) return;

        latest.current.onPhaseChange?.("proxy-ready");

        const hostContext = buildInitialContext(latest.current);
        const bridge = new AppBridge(null, HOST_INFO, HOST_CAPABILITIES, {
          hostContext,
        });

        bridge.oncalltool = async (params) =>
          latest.current.proxyToolCall({
            serverName: latest.current.serverName,
            toolName: params.name,
            args: params.arguments,
          });

        bridge.onreadresource = async (params) =>
          latest.current.proxyResourceRead({
            serverName: latest.current.serverName,
            uri: params.uri,
          });

        bridge.onopenlink = async (params) => {
          await latest.current.openLink({ url: params.url });
          return {};
        };

        bridge.onmessage = async (params) => {
          const text = params.content
            .filter(
              (block): block is { type: "text"; text: string } =>
                block.type === "text",
            )
            .map((block) => block.text)
            .join("\n");
          if (text) latest.current.onAppMessage?.(text);
          return {};
        };

        bridge.onrequestdisplaymode = async (params) => {
          if (params.mode === "inline" || params.mode === "fullscreen") {
            latest.current.onDisplayModeChange?.(params.mode);
            return { mode: params.mode };
          }
          return { mode: latest.current.displayMode };
        };

        bridge.onsizechange = (params) => {
          if (typeof params.height === "number" && params.height > 0) {
            latest.current.onSizeChange?.(params.height);
          }
        };

        bridge.onloggingmessage = (params) => {
          log.info("App log", {
            server: latest.current.serverName,
            level: params.level,
            data: params.data,
          });
        };

        bridge.oninitialized = () => {
          if (cleanedUp) return;
          initializedRef.current = true;
          latest.current.onPhaseChange?.("initialized");

          if (latest.current.toolInput) {
            bridge.sendToolInput({ arguments: latest.current.toolInput });
          }
          if (latest.current.existingToolResult) {
            bridge.sendToolResult(latest.current.existingToolResult);
          }

          for (const fn of pendingRef.current) fn(bridge);
          pendingRef.current = [];
        };

        await bridge.connect(transport);
        bridgeRef.current = bridge;

        await bridge.sendSandboxResourceReady({
          html: uiResource.html,
          csp: uiResource.csp,
          permissions: uiResource.permissions,
        });

        if (!cleanedUp) latest.current.onPhaseChange?.("resource-sent");
      } catch (err) {
        log.error("Failed to initialize mobile MCP bridge", err);
        if (!cleanedUp) latest.current.onPhaseChange?.("error");
      }
    };

    void setup();

    return () => {
      cleanedUp = true;
      const bridge = bridgeRef.current;
      const transport = transportRef.current;
      bridgeRef.current = null;
      transportRef.current = null;
      initializedRef.current = false;
      pendingRef.current = [];
      if (bridge) {
        bridge.teardownResource({}).catch(() => {});
        bridge.close().catch(() => {});
      }
      if (transport) {
        transport.close().catch(() => {});
      }
    };
    // Re-run when the resource object identity changes (React Query gives a
    // stable reference per cache key). Everything else flows through
    // `latest.current` inside the handlers.
  }, [uiResourceProp, webViewRef]);

  // Host context changes (theme, display mode, container size, safe areas).
  useEffect(() => {
    if (!initializedRef.current || !bridgeRef.current) return;
    const bridge = bridgeRef.current;
    const hostStyles = buildMcpHostStyles(args.themeColors, args.isDarkMode);
    bridge.sendHostContextChange({
      theme: args.isDarkMode ? "dark" : "light",
      styles: { variables: hostStyles.variables, css: hostStyles.css },
      displayMode: args.displayMode,
      containerDimensions: {
        width: args.containerWidth,
        height: 320,
      },
      safeAreaInsets: {
        top: args.safeAreaInsets.top,
        right: args.safeAreaInsets.right,
        bottom: args.safeAreaInsets.bottom,
        left: args.safeAreaInsets.left,
      },
    });
  }, [
    args.isDarkMode,
    args.displayMode,
    args.containerWidth,
    args.themeColors,
    args.safeAreaInsets,
  ]);

  const handleWebViewMessage = useCallback((payload: string) => {
    transportRef.current?.acceptIncoming(payload);
  }, []);

  const sendWhenReady = useCallback((fn: (bridge: AppBridge) => void) => {
    if (initializedRef.current && bridgeRef.current) {
      fn(bridgeRef.current);
    } else {
      pendingRef.current.push(fn);
    }
  }, []);

  return { handleWebViewMessage, sendWhenReady };
}
