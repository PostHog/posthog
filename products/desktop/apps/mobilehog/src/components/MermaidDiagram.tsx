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
  inlineScriptSource,
  mermaidHtml,
  parseMermaidMessage,
  rememberSize,
} from "@/lib/mermaid";
import { colors } from "@/lib/theme";

const PADDING = 12;
const PENDING_HEIGHT = 120;
const SIZE_CACHE_LIMIT = 50;

let bundle: string | null = null;

// Metro exports the prebuilt browser bundle as a string (see metro.transformer.js).
function mermaidBundle(): string {
  bundle ??= inlineScriptSource(
    require("mermaid/dist/mermaid.min.js") as string,
  );
  return bundle;
}

// Remounted rows keep their height instead of jumping while the WebView loads.
const sizes = new Map<string, DiagramSize>();

interface MermaidDiagramProps {
  code: string;
  fallback: ReactNode;
}

// Keyed by theme and code, so a new diagram starts without the old failure or size.
export function MermaidDiagram(props: MermaidDiagramProps): ReactNode {
  const dark = useColorScheme() === "dark";
  const key = `${dark ? "dark" : "light"}\n${props.code}`;
  return <DiagramView key={key} cacheKey={key} dark={dark} {...props} />;
}

interface DiagramViewProps extends MermaidDiagramProps {
  cacheKey: string;
  dark: boolean;
}

function DiagramView({
  code,
  fallback,
  cacheKey,
  dark,
}: DiagramViewProps): ReactNode {
  const html = useMemo(
    () => mermaidHtml(code, dark, mermaidBundle()),
    [code, dark],
  );
  const [width, setWidth] = useState(0);
  const [size, setSize] = useState(() => sizes.get(cacheKey) ?? null);
  const [failed, setFailed] = useState(false);

  if (failed || hasRemoteImageNode(code)) return fallback;

  const fail = () => setFailed(true);
  const onMessage = (data: string) => {
    const message = parseMermaidMessage(data);
    if (message?.type === "size") {
      const next = { width: message.width, height: message.height };
      rememberSize(sizes, cacheKey, next, SIZE_CACHE_LIMIT);
      setSize(next);
    } else if (message?.type === "error") {
      fail();
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
            source={{ html }}
            originWhitelist={["*"]}
            onShouldStartLoadWithRequest={(request) =>
              request.url.startsWith("about:")
            }
            onMessage={(event) => onMessage(event.nativeEvent.data)}
            onError={fail}
            onContentProcessDidTerminate={fail}
            onRenderProcessGone={fail}
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
