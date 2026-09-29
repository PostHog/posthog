import { parseObjectTags } from "@posthog/core/inbox/objectTags";
import {
  isRasterImageFile,
  isSafeExternalUrl,
  unescapeXmlAttr,
} from "@posthog/shared";
import {
  type ColorValue,
  Linking,
  StyleSheet,
  Text,
  useColorScheme,
  View,
} from "react-native";
import { ChatImage } from "@/components/ChatImage";
import { InsightCard } from "@/components/InsightCard";
import MermaidDiagram from "@/components/MermaidDiagram";
import { artifactDownloadPath } from "@/lib/images";
import { colors, fonts } from "@/lib/theme";

interface MarkdownProps {
  text: string;
  color?: ColorValue;
}

type Segment =
  | { kind: "text"; value: string }
  | { kind: "bold"; value: string }
  | { kind: "code"; value: string }
  | { kind: "link"; value: string; href: string };

const INLINE = /(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*)/g;

function parseInline(line: string): Segment[] {
  const segments: Segment[] = [];
  let lastIndex = 0;
  for (const match of line.matchAll(INLINE)) {
    const index = match.index ?? 0;
    if (index > lastIndex)
      segments.push({ kind: "text", value: line.slice(lastIndex, index) });
    const token = match[0];
    if (token.startsWith("**"))
      segments.push({ kind: "bold", value: token.slice(2, -2) });
    else if (token.startsWith("`"))
      segments.push({ kind: "code", value: token.slice(1, -1) });
    else {
      const link = /\[([^\]]+)\]\(([^)]+)\)/.exec(token);
      if (link) segments.push({ kind: "link", value: link[1], href: link[2] });
    }
    lastIndex = index + token.length;
  }
  if (lastIndex < line.length)
    segments.push({ kind: "text", value: line.slice(lastIndex) });
  return segments;
}

function Inline({ line, color }: { line: string; color: ColorValue }) {
  return (
    <>
      {parseInline(line).map((segment, index) => {
        const key = `${index}-${segment.value}`;
        switch (segment.kind) {
          case "bold":
            return (
              <Text key={key} style={{ fontFamily: fonts.sansSemi, color }}>
                {segment.value}
              </Text>
            );
          case "code":
            return (
              <Text key={key} style={styles.inlineCode}>
                {segment.value}
              </Text>
            );
          case "link":
            return (
              <Text
                key={key}
                style={styles.link}
                onPress={() => {
                  if (isSafeExternalUrl(segment.href))
                    void Linking.openURL(segment.href).catch(() => {});
                }}
              >
                <Inline line={segment.value} color={colors.accent} />
              </Text>
            );
          default:
            return <Text key={key}>{segment.value}</Text>;
        }
      })}
    </>
  );
}

type NodeType =
  | { type: "code"; lang: string; lines: string[] }
  | { type: "heading"; level: number; text: string }
  | { type: "bullet"; text: string; ordered: boolean; index: number }
  | { type: "quote"; text: string }
  | { type: "paragraph"; text: string }
  | { type: "gap" };

function parseBlocks(text: string): NodeType[] {
  const nodes: NodeType[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let code: { lang: string; lines: string[] } | null = null;
  let paragraph: string[] = [];
  let ordinal = 0;
  let objectBlock: { tag: string; lines: string[] } | null = null;

  const flush = (): void => {
    if (paragraph.length > 0) {
      nodes.push({ type: "paragraph", text: paragraph.join("\n") });
      paragraph = [];
    }
  };

  for (const line of lines) {
    if (objectBlock) {
      objectBlock.lines.push(line);
      if (
        line.includes(`</${objectBlock.tag}>`) ||
        line.trimEnd().endsWith("/>")
      ) {
        nodes.push({ type: "paragraph", text: objectBlock.lines.join("\n") });
        objectBlock = null;
      }
      continue;
    }
    if (code) {
      if (line.trim().startsWith("```")) {
        nodes.push({ type: "code", ...code });
        code = null;
      } else {
        code.lines.push(line);
      }
      continue;
    }
    const fence = /^\s*```(\w*)/.exec(line);
    if (fence) {
      flush();
      code = { lang: fence[1] ?? "", lines: [] };
      continue;
    }
    const objectStart = /^\s*<(hogql|insight)\b/.exec(line);
    if (
      objectStart &&
      !line.includes(`</${objectStart[1]}>`) &&
      !line.trimEnd().endsWith("/>")
    ) {
      flush();
      objectBlock = { tag: objectStart[1], lines: [line] };
      continue;
    }
    if (line.trim() === "") {
      flush();
      ordinal = 0;
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      nodes.push({
        type: "heading",
        level: heading[1].length,
        text: heading[2],
      });
      continue;
    }
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    if (bullet) {
      flush();
      nodes.push({ type: "bullet", text: bullet[1], ordered: false, index: 0 });
      continue;
    }
    const numbered = /^\s*(\d+)[.)]\s+(.*)$/.exec(line);
    if (numbered) {
      flush();
      ordinal += 1;
      nodes.push({
        type: "bullet",
        text: numbered[2],
        ordered: true,
        index: ordinal,
      });
      continue;
    }
    const quote = /^\s*>\s?(.*)$/.exec(line);
    if (quote) {
      flush();
      nodes.push({ type: "quote", text: quote[1] });
      continue;
    }
    paragraph.push(line.trim());
  }
  if (code) nodes.push({ type: "code", ...code });
  flush();
  return nodes;
}

function RichText({ text, color }: { text: string; color: ColorValue }) {
  return (
    <View style={{ gap: 8 }}>
      {parseObjectTags(text).flatMap((segment, index) => {
        if (segment.type === "tag")
          return [
            <InsightCard
              key={`${index}-${segment.ref.kind}-${segment.ref.id}`}
              reference={segment.ref}
            />,
          ];
        const parts = segment.value.split(
          /(!?\[[^\]]*\]\([^)]+\)|<file\s+[^>]*\/>)/g,
        );
        return parts.filter(Boolean).map((part, partIndex) => {
          const key = `${index}-${partIndex}`;
          const image = /^!?\[([^\]]*)\]\(([^)]+)\)$/.exec(part);
          if (
            image &&
            (part.startsWith("!") ||
              isRasterImageFile(image[2].split("?")[0]) ||
              artifactDownloadPath(image[2]))
          )
            return (
              <ChatImage key={key} uri={image[2]} label={image[1] || "Image"} />
            );
          const file = /^<file\s+[^>]*?path="([^"]+)"[^>]*\/>$/.exec(part);
          const path = file ? unescapeXmlAttr(file[1]) : null;
          if (
            path &&
            (isRasterImageFile(path.split("?")[0]) ||
              artifactDownloadPath(path))
          )
            return (
              <ChatImage key={key} uri={path} label={path.split("/").pop()} />
            );
          return (
            <Text key={key} style={[styles.body, { color }]} selectable>
              <Inline line={part} color={color} />
            </Text>
          );
        });
      })}
    </View>
  );
}

export function Markdown({ text, color = colors.ink }: MarkdownProps) {
  const nodes = parseBlocks(text);
  const dark = useColorScheme() === "dark";
  return (
    <View style={styles.root}>
      {nodes.map((node, index) => {
        const key = `${index}-${node.type}`;
        switch (node.type) {
          case "code":
            if (node.lang.toLowerCase() === "mermaid")
              return (
                <View key={key} style={styles.codeBlock}>
                  <MermaidDiagram
                    code={node.lines.join("\n")}
                    dark={dark}
                    dom={{
                      useExpoDOMWebView: false,
                      matchContents: true,
                      scrollEnabled: false,
                      style: { backgroundColor: "transparent", minHeight: 160 },
                      allowUniversalAccessFromFileURLs: false,
                      javaScriptCanOpenWindowsAutomatically: false,
                      setSupportMultipleWindows: false,
                      injectedJavaScriptBeforeContentLoaded: `(() => {
                    const apply = () => {
                      if (!document.head) return;
                      const meta = document.createElement('meta');
                      meta.httpEquiv = 'Content-Security-Policy';
                      meta.content = "img-src data:; connect-src 'self'; font-src 'self' data:; media-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
                      document.head.append(meta);
                      observer.disconnect();
                    };
                    const observer = new MutationObserver(apply);
                    observer.observe(document.documentElement || document, { childList: true, subtree: true });
                    apply();
                  })(); true;`,
                    }}
                  />
                </View>
              );
            return (
              <View key={key} style={styles.codeBlock}>
                {node.lang ? (
                  <Text style={styles.codeLang}>{node.lang}</Text>
                ) : null}
                <Text style={styles.codeText} selectable>
                  {node.lines.join("\n")}
                </Text>
              </View>
            );
          case "heading":
            return (
              <Text
                key={key}
                style={[
                  styles.heading,
                  {
                    fontFamily: fonts.sans,
                    fontSize: node.level <= 2 ? 19 : 16,
                    color,
                  },
                ]}
              >
                <Inline line={node.text} color={color} />
              </Text>
            );
          case "bullet":
            return (
              <View key={key} style={styles.bulletRow}>
                <Text style={[styles.bulletMark, { color }]}>
                  {node.ordered ? `${node.index}.` : "•"}
                </Text>
                <View style={styles.bulletText}>
                  <RichText text={node.text} color={color} />
                </View>
              </View>
            );
          case "quote":
            return (
              <View key={key} style={styles.quote}>
                <Text style={[styles.body, { color: colors.inkSoft }]}>
                  <Inline line={node.text} color={colors.inkSoft} />
                </Text>
              </View>
            );
          case "paragraph":
            return <RichText key={key} text={node.text} color={color} />;
          default:
            return null;
        }
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { gap: 8 },
  body: { fontFamily: fonts.sans, fontSize: 16, lineHeight: 24 },
  heading: { fontFamily: fonts.sansSemi, lineHeight: 26, marginTop: 4 },
  bulletRow: { flexDirection: "row", gap: 8, paddingLeft: 4 },
  bulletMark: {
    fontFamily: fonts.sans,
    fontSize: 16,
    lineHeight: 24,
    minWidth: 14,
  },
  bulletText: { flex: 1 },
  quote: {
    borderLeftWidth: 2,
    borderLeftColor: colors.line,
    paddingLeft: 12,
  },
  codeBlock: {
    backgroundColor: colors.code,
    borderRadius: 12,
    padding: 12,
    gap: 4,
  },
  codeLang: {
    fontFamily: fonts.monoMedium,
    fontSize: 10,
    color: colors.inkMute,
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  codeText: {
    fontFamily: fonts.mono,
    fontSize: 13,
    lineHeight: 19,
    color: colors.ink,
  },
  inlineCode: {
    fontFamily: fonts.mono,
    fontSize: 14,
    backgroundColor: colors.code,
    color: colors.ink,
  },
  link: { color: colors.accent, textDecorationLine: "underline" },
});
