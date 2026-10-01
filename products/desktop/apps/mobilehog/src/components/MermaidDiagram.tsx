import { type ReactNode, useMemo, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  useColorScheme,
  View,
} from "react-native";
import WebView from "react-native-webview";
import {
  type DiagramSize,
  hasRemoteImageNode,
  mermaidHtml,
  parseMermaidMessage,
} from "@/lib/mermaid";
import { colors } from "@/lib/theme";

const PADDING = 12;
const PENDING_HEIGHT = 120;

let bundle: string | null = null;

// Metro exports the prebuilt browser bundle as a string (see metro.transformer.js).
function mermaidBundle(): string {
  bundle ??= require("mermaid/dist/mermaid.min.js") as string;
  return bundle;
}

// Remounted rows keep their height instead of jumping while the WebView loads.
const sizes = new Map<string, DiagramSize>();

interface MermaidDiagramProps {
  code: string;
  fallback: ReactNode;
}

export function MermaidDiagram({ code, fallback }: MermaidDiagramProps) {
  const dark = useColorScheme() === "dark";
  const key = `${dark ? "dark" : "light"}\n${code}`;
  const html = useMemo(() => mermaidHtml(code, dark), [code, dark]);
  const [width, setWidth] = useState(0);
  const [size, setSize] = useState(() => sizes.get(key) ?? null);
  const [failed, setFailed] = useState(false);

  if (failed || hasRemoteImageNode(code)) return fallback;

  const onMessage = (data: string) => {
    const message = parseMermaidMessage(data);
    if (message?.type === "size") {
      const next = { width: message.width, height: message.height };
      sizes.set(key, next);
      setSize(next);
    } else if (message?.type === "error") {
      setFailed(true);
    }
  };

  return (
    <View
      style={styles.frame}
      onLayout={(event) =>
        setWidth(event.nativeEvent.layout.width - PADDING * 2)
      }
    >
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.content}
      >
        {width > 0 ? (
          <WebView
            key={key}
            source={{ html }}
            injectedJavaScriptBeforeContentLoaded={mermaidBundle()}
            originWhitelist={["*"]}
            onShouldStartLoadWithRequest={(request) =>
              request.url.startsWith("about:")
            }
            onMessage={(event) => onMessage(event.nativeEvent.data)}
            javaScriptEnabled
            scrollEnabled={false}
            bounces={false}
            setSupportMultipleWindows={false}
            showsHorizontalScrollIndicator={false}
            showsVerticalScrollIndicator={false}
            style={[
              styles.webview,
              size ?? { width, height: PENDING_HEIGHT, opacity: 0 },
            ]}
          />
        ) : (
          <View style={{ height: PENDING_HEIGHT }} />
        )}
      </ScrollView>
      {size ? null : (
        <View pointerEvents="none" style={styles.spinner}>
          <ActivityIndicator color={colors.inkMute} />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    backgroundColor: colors.code,
    borderRadius: 12,
    overflow: "hidden",
  },
  content: {
    flexGrow: 1,
    justifyContent: "center",
    padding: PADDING,
  },
  webview: { backgroundColor: "transparent" },
  spinner: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
    justifyContent: "center",
  },
});
