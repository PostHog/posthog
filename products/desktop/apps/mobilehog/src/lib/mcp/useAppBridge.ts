import {
  AppBridge,
  type McpUiDisplayMode,
  type McpUiHostCapabilities,
  type McpUiHostContext,
  type McpUiResourceCsp,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type { CallToolResult, Tool } from "@modelcontextprotocol/sdk/types.js";
import { applyCspToHtml } from "@posthog/core/mcp-apps/csp";
import { isSafeExternalUrl } from "@posthog/shared";
import * as WebBrowser from "expo-web-browser";
import { useCallback, useEffect, useRef } from "react";
import { Platform } from "react-native";
import type { EdgeInsets } from "react-native-safe-area-context";
import type WebView from "react-native-webview";
import { callMcpTool, readMcpResource } from "@/lib/mcp/client";
import { buildHostStyles } from "@/lib/mcp/theme";
import { WebViewTransport } from "@/lib/mcp/webViewTransport";

export type Phase = "loading" | "proxy-ready" | "initialized" | "error";

export interface UiResource {
  uri: string;
  html: string;
  csp?: McpUiResourceCsp;
  permissions?: Record<string, Record<string, unknown>>;
}

interface Args {
  webViewRef: { current: WebView | null };
  resource: UiResource | null | undefined;
  tool: Tool | null | undefined;
  toolInput: Record<string, unknown> | undefined;
  toolResult: CallToolResult | null;
  dark: boolean;
  displayMode: McpUiDisplayMode;
  width: number;
  insets: EdgeInsets;
  onPhase: (phase: Phase) => void;
  onHeight: (height: number) => void;
  onDisplayMode: (mode: McpUiDisplayMode) => void;
}

const HOST_INFO = { name: "mobilehog", version: "1.0.0" };
const CAPABILITIES: McpUiHostCapabilities = {
  openLinks: {},
  serverTools: {},
  serverResources: {},
  logging: {},
  message: { text: {} },
  sandbox: {},
};

function hostContext(args: Args): McpUiHostContext {
  const styles = buildHostStyles(args.dark);
  return {
    theme: args.dark ? "dark" : "light",
    styles,
    availableDisplayModes: ["inline", "fullscreen"],
    displayMode: args.displayMode,
    containerDimensions: { width: args.width, height: 320 },
    locale: "en-US",
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    userAgent: `mobilehog/${Platform.OS}`,
    platform: "mobile",
    deviceCapabilities: { touch: true, hover: false },
    safeAreaInsets: args.insets,
    ...(args.tool ? { toolInfo: { tool: args.tool } } : {}),
  };
}

// One ext-apps AppBridge bound to a WebView: the proxy page relays JSON-RPC to
// the sandboxed app, and tool or resource calls round-trip to the MCP server.
export function useAppBridge(args: Args): {
  onWebViewMessage: (payload: string) => void;
} {
  const transportRef = useRef<WebViewTransport | null>(null);
  const bridgeRef = useRef<AppBridge | null>(null);
  const latest = useRef(args);
  latest.current = args;

  const { webViewRef, resource } = args;
  useEffect(() => {
    if (!resource) return;
    let gone = false;

    const setup = async () => {
      const transport = new WebViewTransport(webViewRef);
      const ready = new Promise<void>((resolve) => {
        const inner = transport.onmessage;
        transport.onmessage = (msg) => {
          if (
            (msg as { method?: string }).method ===
            "ui/notifications/sandbox-proxy-ready"
          ) {
            transport.onmessage = inner;
            resolve();
            return;
          }
          inner?.(msg);
        };
      });
      await transport.start();
      transportRef.current = transport;
      await ready;
      if (gone) return;
      latest.current.onPhase("proxy-ready");

      const bridge = new AppBridge(null, HOST_INFO, CAPABILITIES, {
        hostContext: hostContext(latest.current),
      });
      bridge.oncalltool = (params) =>
        callMcpTool(params.name, params.arguments);
      bridge.onreadresource = (params) => readMcpResource(params.uri);
      bridge.onopenlink = async (params) => {
        if (isSafeExternalUrl(params.url)) {
          await WebBrowser.openBrowserAsync(params.url);
        }
        return {};
      };
      bridge.onmessage = async () => ({});
      bridge.onrequestdisplaymode = async (params) => {
        if (params.mode === "inline" || params.mode === "fullscreen") {
          latest.current.onDisplayMode(params.mode);
          return { mode: params.mode };
        }
        return { mode: latest.current.displayMode };
      };
      bridge.onsizechange = (params) => {
        if (typeof params.height === "number" && params.height > 0) {
          latest.current.onHeight(params.height);
        }
      };
      bridge.oninitialized = () => {
        if (gone) return;
        latest.current.onPhase("initialized");
        if (latest.current.toolInput) {
          bridge.sendToolInput({ arguments: latest.current.toolInput });
        }
        if (latest.current.toolResult) {
          bridge.sendToolResult(latest.current.toolResult);
        }
      };
      await bridge.connect(transport);
      bridgeRef.current = bridge;
      await bridge.sendSandboxResourceReady({
        html: applyCspToHtml(resource.html, resource.csp),
        csp: resource.csp,
        permissions: resource.permissions,
      });
    };

    setup().catch(() => {
      if (!gone) latest.current.onPhase("error");
    });

    return () => {
      gone = true;
      bridgeRef.current?.close().catch(() => {});
      transportRef.current?.close().catch(() => {});
      bridgeRef.current = null;
      transportRef.current = null;
    };
  }, [resource, webViewRef]);

  // Theme, size and display mode changes flow to a live app.
  useEffect(() => {
    const bridge = bridgeRef.current;
    if (!bridge) return;
    bridge.sendHostContextChange({
      theme: args.dark ? "dark" : "light",
      styles: buildHostStyles(args.dark),
      displayMode: args.displayMode,
      containerDimensions: { width: args.width, height: 320 },
      safeAreaInsets: args.insets,
    });
  }, [args.dark, args.displayMode, args.width, args.insets]);

  const onWebViewMessage = useCallback((payload: string) => {
    transportRef.current?.acceptIncoming(payload);
  }, []);

  return { onWebViewMessage };
}
