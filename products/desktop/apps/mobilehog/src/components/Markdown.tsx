import { parseObjectTags } from "@posthog/core/inbox/objectTags";
import {
  isRasterImageFile,
  isSafeExternalUrl,
  unescapeXmlAttr,
} from "@posthog/shared";
import { Lexer, type Token, type Tokens } from "marked";
import { Fragment, type ReactNode, useMemo } from "react";
import {
  type ColorValue,
  Linking,
  ScrollView,
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

function openLink(href: string): void {
  if (isSafeExternalUrl(href)) void Linking.openURL(href).catch(() => {});
}

function Inline({ tokens }: { tokens: Token[] }) {
  return (
    <>
      {tokens.map((token, index) => {
        const key = `${token.type}-${index}`;
        const children =
          "tokens" in token && token.tokens ? (
            <Inline key={key} tokens={token.tokens ?? []} />
          ) : (
            unescapeXmlAttr("text" in token ? token.text : token.raw)
          );
        switch (token.type) {
          case "strong":
            return (
              <Text key={key} style={{ fontWeight: "600" }}>
                {children}
              </Text>
            );
          case "em":
            return (
              <Text key={key} style={{ fontStyle: "italic" }}>
                {children}
              </Text>
            );
          case "del":
            return (
              <Text key={key} style={{ textDecorationLine: "line-through" }}>
                {children}
              </Text>
            );
          case "codespan":
            return (
              <Text key={key} style={styles.inlineCode}>
                {unescapeXmlAttr(token.text)}
              </Text>
            );
          case "link":
            return (
              <Text
                key={key}
                accessibilityRole="link"
                style={styles.link}
                onPress={() => openLink(token.href)}
              >
                {children}
              </Text>
            );
          case "br":
            return <Text key={key}>{"\n"}</Text>;
          default:
            return <Fragment key={key}>{children}</Fragment>;
        }
      })}
    </>
  );
}

function RichText({
  text,
  color,
  tokens,
}: {
  text: string;
  color: ColorValue;
  tokens?: Token[];
}) {
  const nodes: ReactNode[] = [];
  const segments = parseObjectTags(text);
  for (const segment of segments) {
    if (segment.type === "tag") {
      nodes.push(<InsightCard key={nodes.length} reference={segment.ref} />);
      continue;
    }
    let inline: Token[] = [];
    const flush = (): void => {
      if (!inline.length) return;
      nodes.push(
        <Text key={nodes.length} style={[styles.body, { color }]} selectable>
          <Inline tokens={inline} />
        </Text>,
      );
      inline = [];
    };
    for (const token of tokens && segments.length === 1
      ? tokens
      : Lexer.lexInline(segment.value, { gfm: true })) {
      const file =
        token.type === "html"
          ? /^<file\s+[^>]*?path="([^"]+)"[^>]*\/>$/.exec(token.raw.trim())
          : null;
      const href = file
        ? unescapeXmlAttr(file[1])
        : token.type === "image" || token.type === "link"
          ? token.href
          : null;
      if (
        href &&
        (token.type === "image" ||
          isRasterImageFile(href.split("?")[0]) ||
          artifactDownloadPath(href))
      ) {
        flush();
        nodes.push(
          <ChatImage
            key={nodes.length}
            uri={href}
            label={("text" in token && token.text) || href.split("/").pop()}
          />,
        );
      } else {
        inline.push(token);
      }
    }
    flush();
  }
  return <View style={{ gap: 8 }}>{nodes}</View>;
}

function Code({ code, lang }: { code: string; lang?: string }) {
  const dark = useColorScheme() === "dark";
  if (lang?.toLowerCase() === "mermaid")
    return (
      <View style={styles.codeBlock}>
        <MermaidDiagram
          code={code}
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
    <View style={styles.codeBlock}>
      {lang ? <Text style={styles.codeLang}>{lang}</Text> : null}
      <ScrollView horizontal>
        <Text style={styles.codeText} selectable>
          {code}
        </Text>
      </ScrollView>
    </View>
  );
}

function Blocks({ tokens, color }: { tokens: Token[]; color: ColorValue }) {
  return (
    <View style={styles.root}>
      {tokens.map((token, index) => {
        const key = `${token.type}-${index}`;
        switch (token.type) {
          case "space":
            return null;
          case "code":
            return <Code key={key} code={token.text} lang={token.lang} />;
          case "heading":
            return (
              <Text
                key={key}
                style={[
                  styles.heading,
                  { fontSize: token.depth <= 2 ? 20 : 17, color },
                ]}
                selectable
              >
                <Inline key={key} tokens={token.tokens ?? []} />
              </Text>
            );
          case "hr":
            return <View key={key} style={styles.rule} />;
          case "blockquote":
            return (
              <View key={key} style={styles.quote}>
                <Blocks tokens={token.tokens ?? []} color={colors.inkSoft} />
              </View>
            );
          case "list": {
            const list = token as Tokens.List;
            return (
              <View key={key} style={{ gap: 8 }}>
                {list.items.map((item, itemIndex) => (
                  <View
                    key={`${itemIndex}-${item.type}`}
                    style={styles.bulletRow}
                  >
                    <Text style={[styles.bulletMark, { color }]}>
                      {item.task
                        ? item.checked
                          ? "☑"
                          : "☐"
                        : list.ordered
                          ? `${Number(list.start) + itemIndex}.`
                          : "•"}
                    </Text>
                    <View style={styles.bulletText}>
                      <Blocks tokens={item.tokens} color={color} />
                    </View>
                  </View>
                ))}
              </View>
            );
          }
          case "table": {
            const table = token as Tokens.Table;
            return (
              <ScrollView
                key={key}
                horizontal
                accessibilityLabel="Table. Scroll horizontally to read all columns."
              >
                <View style={styles.table}>
                  {[table.header, ...table.rows].map((row, rowIndex) => (
                    <View
                      key={`${rowIndex}-${row[0]?.text}`}
                      style={[
                        styles.tableRow,
                        rowIndex === 0 && styles.tableHeader,
                      ]}
                    >
                      {row.map((cell, column) => (
                        <View
                          key={`${column}-${table.header[column]?.text}`}
                          style={styles.cell}
                        >
                          <Text
                            selectable
                            style={[
                              styles.body,
                              {
                                color,
                                textAlign: table.align[column] ?? "left",
                                fontWeight: rowIndex === 0 ? "600" : "400",
                              },
                            ]}
                          >
                            <Inline tokens={cell.tokens} />
                          </Text>
                        </View>
                      ))}
                    </View>
                  ))}
                </View>
              </ScrollView>
            );
          }
          default:
            return (
              <RichText
                key={key}
                text={"text" in token ? token.text : token.raw}
                tokens={"tokens" in token ? token.tokens : undefined}
                color={color}
              />
            );
        }
      })}
    </View>
  );
}

export function Markdown({ text, color = colors.ink }: MarkdownProps) {
  const tokens = useMemo(() => Lexer.lex(text, { gfm: true }), [text]);
  return <Blocks tokens={tokens} color={color} />;
}

const styles = StyleSheet.create({
  root: { gap: 10 },
  table: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: 8,
    overflow: "hidden",
  },
  tableRow: { flexDirection: "row" },
  tableHeader: { backgroundColor: colors.fill },
  cell: {
    width: 180,
    padding: 10,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
  },
  rule: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.line,
    marginVertical: 8,
  },
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
