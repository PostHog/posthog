import type { McpUiDisplayMode } from "@modelcontextprotocol/ext-apps/app-bridge";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { resolveResultResourceUri } from "@posthog/core/mcp-apps/schemas";
import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  useColorScheme,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import WebView from "react-native-webview";
import { GlassCircleButton } from "@/components/Glass";
import { listMcpTools, readMcpResource } from "@/lib/mcp/client";
import { sandboxProxyHtml } from "@/lib/mcp/sandboxProxyHtml";
import {
  type Phase,
  type UiResource,
  useAppBridge,
} from "@/lib/mcp/useAppBridge";
import { colors, fonts, radius } from "@/lib/theme";
import type { Block } from "@/lib/transcript";

const MIN_HEIGHT = 180;
const MAX_HEIGHT = 520;

// Does this tool result come with an MCP UI app to render it?
export function appResourceUri(output: unknown): string | undefined {
  return resolveResultResourceUri(output);
}

function useUiResource(uri: string) {
  return useQuery<UiResource | null>({
    queryKey: ["mcp", "ui-resource", uri],
    queryFn: async () => {
      const read = await readMcpResource(uri);
      const content = read.contents.find((item) => item.uri === uri) as
        | {
            text?: unknown;
            mimeType?: unknown;
            _meta?: Record<string, unknown>;
          }
        | undefined;
      const html = typeof content?.text === "string" ? content.text : null;
      const mime =
        typeof content?.mimeType === "string" ? content.mimeType : "";
      if (!html || !mime.startsWith("text/html")) return null;
      const ui = (content?._meta?.ui ?? {}) as Record<string, unknown>;
      return {
        uri,
        html,
        csp: ui.csp as UiResource["csp"],
        permissions: ui.permissions as UiResource["permissions"],
      };
    },
    staleTime: 5 * 60_000,
  });
}

// Hosts an MCP UI app (a chart, a table) for a finished tool call, inline in
// the transcript with a fullscreen mode.
export function McpAppHost({ block }: { block: Block & { kind: "tool" } }) {
  const uri = appResourceUri(block.output) ?? "";
  const resource = useUiResource(uri);
  const tools = useQuery({ queryKey: ["mcp", "tools"], queryFn: listMcpTools });
  const scheme = useColorScheme();
  const insets = useSafeAreaInsets();
  const webViewRef = useRef<WebView | null>(null);
  const [width, setWidth] = useState(0);
  const [phase, setPhase] = useState<Phase>("loading");
  const [displayMode, setDisplayMode] = useState<McpUiDisplayMode>("inline");
  const [height, setHeight] = useState(MIN_HEIGHT);

  const { onWebViewMessage } = useAppBridge({
    webViewRef,
    resource: resource.data,
    tool: tools.data?.find((tool) => tool.name === (block.toolName ?? "exec")),
    toolInput: block.input,
    toolResult: block.output as CallToolResult | null,
    dark: scheme === "dark",
    displayMode,
    width,
    insets,
    onPhase: setPhase,
    onHeight: setHeight,
    onDisplayMode: setDisplayMode,
  });

  if (resource.isError || phase === "error") {
    return (
      <View style={styles.card}>
        <Text style={styles.muted}>Couldn't load this view.</Text>
      </View>
    );
  }

  const inlineHeight = Math.min(Math.max(height, MIN_HEIGHT), MAX_HEIGHT);
  const app = (
    <View
      onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
      style={[
        styles.card,
        { height: displayMode === "fullscreen" ? "100%" : inlineHeight },
      ]}
    >
      {resource.data ? (
        <WebView
          ref={webViewRef}
          originWhitelist={["*"]}
          source={{ html: sandboxProxyHtml }}
          onMessage={(event) => onWebViewMessage(event.nativeEvent.data)}
          javaScriptEnabled
          domStorageEnabled
          setSupportMultipleWindows={false}
          mixedContentMode="always"
          style={styles.webview}
        />
      ) : null}
      {phase !== "initialized" ? (
        <View pointerEvents="none" style={styles.spinner}>
          <ActivityIndicator color={colors.inkMute} />
        </View>
      ) : null}
      {displayMode === "inline" ? (
        <Pressable
          onPress={() => setDisplayMode("fullscreen")}
          hitSlop={8}
          style={styles.expand}
        >
          <Text style={styles.expandText}>⤢</Text>
        </Pressable>
      ) : null}
    </View>
  );

  if (displayMode === "fullscreen") {
    return (
      <Modal
        visible
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={() => setDisplayMode("inline")}
      >
        <View style={[styles.full, { paddingTop: insets.top + 6 }]}>
          <View style={styles.fullHeader}>
            <GlassCircleButton onPress={() => setDisplayMode("inline")}>
              <Text style={styles.close}>×</Text>
            </GlassCircleButton>
            <Text style={styles.fullTitle} numberOfLines={1}>
              {block.title}
            </Text>
            <View style={{ width: 46 }} />
          </View>
          <View style={[styles.fullBody, { paddingBottom: insets.bottom }]}>
            {app}
          </View>
        </View>
      </Modal>
    );
  }
  return app;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.card,
    overflow: "hidden",
  },
  webview: { flex: 1, backgroundColor: "transparent" },
  spinner: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
    justifyContent: "center",
  },
  muted: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.inkMute,
    padding: 16,
  },
  expand: {
    position: "absolute",
    top: 8,
    right: 8,
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.fill,
  },
  expandText: { fontSize: 16, color: colors.inkSoft },
  full: { flex: 1, backgroundColor: colors.bg },
  fullHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingBottom: 8,
  },
  fullTitle: {
    fontFamily: fonts.sansSemi,
    fontSize: 17,
    color: colors.ink,
    flex: 1,
    textAlign: "center",
  },
  close: { fontSize: 26, lineHeight: 28, color: colors.ink, marginTop: -2 },
  fullBody: { flex: 1, paddingHorizontal: 12 },
});
