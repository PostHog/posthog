import { Text } from "@components/text";
import type { McpUiDisplayMode } from "@modelcontextprotocol/ext-apps/app-bridge";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { isSafeExternalUrl } from "@posthog/shared";
import * as WebBrowser from "expo-web-browser";
import { ArrowsIn, ArrowsOut, Warning } from "phosphor-react-native";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  StyleSheet,
  useColorScheme,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import WebView, { type WebViewMessageEvent } from "react-native-webview";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";
import { useMcpInstallations } from "../hooks";
import { sandboxProxyHtml } from "../sandbox/sandboxProxyHtml";
import { useMcpUiResource } from "../sandbox/useMcpUiResource";
import { type Phase, useMobileAppBridge } from "../sandbox/useMobileAppBridge";
import { getMcpConnectionManager } from "../service";
import { parseMcpToolName } from "../utils/mcpToolName";

interface McpAppHostProps {
  /** Raw tool name from the agent — `mcp__<server>__<tool>`. */
  rawToolName: string;
  /** Args the agent sent to the tool, if any. */
  toolArgs?: Record<string, unknown>;
  /** The tool result the agent already received, if completed. */
  toolResult?: unknown;
  status: "pending" | "running" | "completed" | "error";
}

const log = logger.scope("McpAppHost");

const INLINE_MIN_HEIGHT = 180;
const INLINE_MAX_HEIGHT = 520;

function asCallToolResult(value: unknown): CallToolResult | null {
  if (!value || typeof value !== "object") return null;
  const v = value as { content?: unknown };
  if (!Array.isArray(v.content)) return null;
  return value as CallToolResult;
}

export function McpAppHost(props: McpAppHostProps) {
  const themeColors = useThemeColors();
  const scheme = useColorScheme();
  const isDarkMode = scheme === "dark";
  const insets = useSafeAreaInsets();

  const parsed = useMemo(
    () => parseMcpToolName(props.rawToolName),
    [props.rawToolName],
  );

  const installations = useMcpInstallations();
  const installation = useMemo(() => {
    if (!parsed) return null;
    return (
      installations.data?.find((i) => i.name === parsed.serverName) ?? null
    );
  }, [installations.data, parsed]);

  const uiResource = useMcpUiResource({
    installation,
    toolName: parsed?.toolName ?? "",
  });

  const webViewRef = useRef<WebView | null>(null);
  const [webViewWidth, setWebViewWidth] = useState(0);
  const [phase, setPhase] = useState<Phase>("loading");
  const [displayMode, setDisplayMode] = useState<McpUiDisplayMode>("inline");
  const [iframeHeight, setIframeHeight] = useState(INLINE_MIN_HEIGHT);

  const handleProxyToolCall = useCallback(
    async (args: {
      serverName: string;
      toolName: string;
      args?: Record<string, unknown>;
    }) => {
      if (!installation) {
        throw new Error("MCP installation unavailable");
      }
      return getMcpConnectionManager().callTool({
        installationId: installation.id,
        serverName: installation.name,
        proxyUrl: installation.proxy_url,
        toolName: args.toolName,
        arguments: args.args,
      });
    },
    [installation],
  );

  const handleProxyResourceRead = useCallback(
    async (args: { serverName: string; uri: string }) => {
      if (!installation) {
        throw new Error("MCP installation unavailable");
      }
      return getMcpConnectionManager().readResource({
        installationId: installation.id,
        serverName: installation.name,
        proxyUrl: installation.proxy_url,
        uri: args.uri,
      });
    },
    [installation],
  );

  const handleOpenLink = useCallback(async (args: { url: string }) => {
    if (!isSafeExternalUrl(args.url)) {
      log.warn("Blocked external URL with unsafe scheme", args.url);
      return;
    }
    await WebBrowser.openBrowserAsync(args.url);
  }, []);

  const { handleWebViewMessage } = useMobileAppBridge({
    webViewRef,
    uiResource: uiResource.data?.resource ?? null,
    serverName: parsed?.serverName ?? "",
    toolDefinition: uiResource.data?.tool ?? null,
    toolInput: props.toolArgs ?? null,
    existingToolResult:
      props.status === "completed" || props.status === "error"
        ? asCallToolResult(props.toolResult)
        : null,
    themeColors,
    isDarkMode,
    displayMode,
    containerWidth: webViewWidth,
    safeAreaInsets: insets,
    onPhaseChange: setPhase,
    onSizeChange: setIframeHeight,
    onDisplayModeChange: setDisplayMode,
    proxyToolCall: handleProxyToolCall,
    proxyResourceRead: handleProxyResourceRead,
    openLink: handleOpenLink,
  });

  const onMessage = useCallback(
    (event: WebViewMessageEvent) => {
      handleWebViewMessage(event.nativeEvent.data);
    },
    [handleWebViewMessage],
  );

  if (!parsed) {
    return null;
  }

  if (installations.isPending) {
    return <LoadingCard themeColors={themeColors} message="Loading…" />;
  }

  if (!installation) {
    return (
      <ErrorCard
        themeColors={themeColors}
        message={`No installed MCP server named "${parsed.serverName}"`}
      />
    );
  }

  if (uiResource.isError) {
    return (
      <ErrorCard
        themeColors={themeColors}
        message={`Couldn't load MCP UI: ${uiResource.error?.message ?? "unknown error"}`}
      />
    );
  }

  if (uiResource.isPending) {
    return <LoadingCard themeColors={themeColors} message="Connecting…" />;
  }

  if (!uiResource.data) {
    // Tool doesn't expose a UI resource — render nothing and fall back to
    // the parent's default tool view.
    return null;
  }

  const inlineHeight = Math.min(
    Math.max(iframeHeight, INLINE_MIN_HEIGHT),
    INLINE_MAX_HEIGHT,
  );

  const webView = (
    <View
      onLayout={(e) => setWebViewWidth(e.nativeEvent.layout.width)}
      className="overflow-hidden rounded-lg border border-gray-5 bg-card"
      style={{
        height: displayMode === "fullscreen" ? "100%" : inlineHeight,
      }}
    >
      <WebView
        ref={webViewRef}
        originWhitelist={["*"]}
        source={{ html: sandboxProxyHtml }}
        onMessage={onMessage}
        javaScriptEnabled
        domStorageEnabled
        allowsInlineMediaPlayback
        scrollEnabled
        setSupportMultipleWindows={false}
        // Allow file-less iframe via document.write inside the sandbox proxy.
        mixedContentMode="always"
        style={{ backgroundColor: "transparent" }}
      />
      {phase !== "initialized" && phase !== "error" ? (
        <View
          pointerEvents="none"
          style={[
            StyleSheet.absoluteFillObject,
            { alignItems: "center", justifyContent: "center" },
          ]}
        >
          <ActivityIndicator color={themeColors.accent[9]} />
        </View>
      ) : null}
    </View>
  );

  return (
    <View className="mb-2">
      <View className="mb-1 flex-row items-center justify-between">
        <Text className="text-[12px] text-gray-10" numberOfLines={1}>
          {parsed.serverName} · {parsed.toolName}
        </Text>
        <Pressable
          onPress={() =>
            setDisplayMode(
              displayMode === "fullscreen" ? "inline" : "fullscreen",
            )
          }
          hitSlop={8}
          className="active:opacity-60"
        >
          {displayMode === "fullscreen" ? (
            <ArrowsIn size={16} color={themeColors.gray[11]} />
          ) : (
            <ArrowsOut size={16} color={themeColors.gray[11]} />
          )}
        </Pressable>
      </View>

      {displayMode === "fullscreen" ? (
        <Modal
          visible
          animationType="slide"
          presentationStyle="fullScreen"
          onRequestClose={() => setDisplayMode("inline")}
        >
          <View
            className="flex-1 bg-background"
            style={{ paddingTop: insets.top }}
          >
            <View className="flex-row items-center justify-between px-4 pb-2">
              <Text className="font-semibold text-[16px] text-gray-12">
                {parsed.toolName}
              </Text>
              <Pressable
                onPress={() => setDisplayMode("inline")}
                hitSlop={8}
                className="active:opacity-60"
              >
                <ArrowsIn size={20} color={themeColors.gray[12]} />
              </Pressable>
            </View>
            <View className="flex-1 px-3 pb-4">{webView}</View>
          </View>
        </Modal>
      ) : (
        webView
      )}
    </View>
  );
}

function LoadingCard({
  themeColors,
  message,
}: {
  themeColors: ReturnType<typeof useThemeColors>;
  message: string;
}) {
  return (
    <View className="mb-2 items-center rounded-lg border border-gray-5 bg-card p-4">
      <ActivityIndicator color={themeColors.accent[9]} />
      <Text className="mt-2 text-[13px] text-gray-11">{message}</Text>
    </View>
  );
}

function ErrorCard({
  themeColors,
  message,
}: {
  themeColors: ReturnType<typeof useThemeColors>;
  message: string;
}) {
  return (
    <View className="mb-2 flex-row items-start gap-2 rounded-lg border border-gray-5 bg-card p-3">
      <Warning size={16} color={themeColors.status.error} />
      <Text className="flex-1 text-[13px] text-gray-12">{message}</Text>
    </View>
  );
}
