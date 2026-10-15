import type { ObjectTagRef } from "@posthog/core/inbox/objectTags";
import { isSafeExternalUrl } from "@posthog/shared";
import type { MarkedToken, Token, Tokens } from "marked";
import { type ReactNode, useMemo, useState } from "react";
import {
  type ColorValue,
  Image,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { MermaidDiagram } from "@/components/MermaidDiagram";
import {
  ObjectCard,
  openObjectUrl,
  useObjectUrl,
} from "@/components/ObjectCard";
import { lexMarkdown, splitImageRuns } from "@/lib/markdown";
import { isClosedFence, isMermaidLang } from "@/lib/mermaid";
import {
  isObjectCardToken,
  isObjectRefToken,
  isObjectTagMarkup,
} from "@/lib/objectTags";
import { colors, fonts } from "@/lib/theme";

interface MarkdownProps {
  text: string;
  color?: ColorValue;
}

function openLink(href: string): void {
  if (isSafeExternalUrl(href)) Linking.openURL(href).catch(() => {});
}

// Kinds without a page in PostHog read as plain text.
function ObjectChip({ target }: { target: ObjectTagRef }): ReactNode {
  const url = useObjectUrl(target.kind, target.id);
  return url ? (
    <Text style={styles.chip} onPress={() => openObjectUrl(url)}>
      {target.label}
    </Text>
  ) : (
    target.label
  );
}

function renderInline(
  tokens: Token[] | undefined,
  color: ColorValue,
  linked = false,
): ReactNode[] {
  return (tokens ?? []).map((raw, index) => {
    const key = String(index);
    if (isObjectRefToken(raw)) {
      return <ObjectChip key={key} target={raw.ref} />;
    }
    const token = raw as MarkedToken;
    switch (token.type) {
      case "strong":
        return (
          <Text key={key} style={{ fontFamily: fonts.sansSemi, color }}>
            {renderInline(token.tokens, color, linked)}
          </Text>
        );
      case "em":
        return (
          <Text key={key} style={{ fontFamily: fonts.sansItalic, color }}>
            {renderInline(token.tokens, color, linked)}
          </Text>
        );
      case "del":
        return (
          <Text key={key} style={styles.strike}>
            {renderInline(token.tokens, color, linked)}
          </Text>
        );
      case "codespan":
        return (
          <Text key={key} style={styles.inlineCode}>
            {token.text}
          </Text>
        );
      case "link":
        return (
          <Text
            key={key}
            style={styles.link}
            onPress={() => openLink(token.href)}
          >
            {renderInline(token.tokens, colors.accent, true)}
          </Text>
        );
      case "image":
        return !linked && isSafeExternalUrl(token.href) ? (
          <Text
            key={key}
            style={styles.link}
            onPress={() => openLink(token.href)}
          >
            {token.text || token.href}
          </Text>
        ) : (
          token.text
        );
      case "br":
        return "\n";
      case "html":
        return isObjectTagMarkup(token.text) ? null : token.text;
      case "text":
        return token.tokens ? (
          <Text key={key}>{renderInline(token.tokens, color, linked)}</Text>
        ) : (
          token.text
        );
      default:
        return "text" in token ? String(token.text) : "";
    }
  });
}

// Width from the longest cell, so columns line up without measuring.
function columnWidths(rows: string[][]): number[] {
  const count = Math.max(...rows.map((row) => row.length));
  return Array.from({ length: count }, (_, column) => {
    const longest = Math.max(...rows.map((row) => row[column]?.length ?? 0));
    return Math.min(240, Math.max(72, longest * 7.5 + 24));
  });
}

function Table({ token, color }: { token: Tokens.Table; color: ColorValue }) {
  const rows = [token.header, ...token.rows];
  const widths = columnWidths(rows.map((row) => row.map((cell) => cell.text)));
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}>
      <View style={styles.table}>
        {rows.map((row, rowIndex) => (
          <View
            key={String(rowIndex)}
            style={[
              styles.tableRow,
              rowIndex > 0 && styles.tableRowDivided,
              rowIndex === 0 && styles.tableHeader,
            ]}
          >
            {widths.map((width, column) => (
              <Text
                key={String(column)}
                style={[
                  styles.tableCell,
                  rowIndex === 0 && styles.tableHeaderText,
                  { width, color },
                ]}
                selectable
              >
                {renderInline(row[column]?.tokens, color)}
              </Text>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

function List({ token, color }: { token: Tokens.List; color: ColorValue }) {
  const start = typeof token.start === "number" ? token.start : 1;
  return (
    <View style={styles.list}>
      {token.items.map((item, index) => (
        <View key={String(index)} style={styles.bulletRow}>
          <Text style={[styles.bulletMark, { color }]}>
            {token.ordered ? `${start + index}.` : "•"}
          </Text>
          <View style={styles.bulletText}>
            {renderBlocks(item.tokens, color)}
          </View>
        </View>
      ))}
    </View>
  );
}

interface ImageSize {
  width: number;
  height: number;
}

function MarkdownImage({ token }: { token: Tokens.Image }) {
  const [size, setSize] = useState<ImageSize | null>(null);
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <Text
        style={[styles.body, styles.link]}
        onPress={() => openLink(token.href)}
      >
        {token.text || token.href}
      </Text>
    );
  }
  return (
    <Pressable
      onPress={() => openLink(token.href)}
      accessibilityRole="imagebutton"
      accessibilityLabel={token.text || undefined}
    >
      <Image
        source={{ uri: token.href }}
        onLoad={(event) => {
          const { width, height } = event.nativeEvent.source;
          if (width > 0 && height > 0) setSize({ width, height });
        }}
        onError={() => setFailed(true)}
        style={[
          styles.image,
          size
            ? { aspectRatio: size.width / size.height }
            : styles.imagePending,
        ]}
      />
    </Pressable>
  );
}

function Paragraph({ tokens, color }: { tokens: Token[]; color: ColorValue }) {
  const runs = splitImageRuns(tokens);
  if (!runs.some((run) => run.kind === "image")) {
    return (
      <Text style={[styles.body, { color }]} selectable>
        {renderInline(tokens, color)}
      </Text>
    );
  }
  return (
    <View style={styles.runs}>
      {runs.map((run, index) =>
        run.kind === "image" ? (
          <MarkdownImage key={`${index}-${run.token.href}`} token={run.token} />
        ) : (
          <Text key={String(index)} style={[styles.body, { color }]} selectable>
            {renderInline(run.tokens, color)}
          </Text>
        ),
      )}
    </View>
  );
}

function CodeBlock({ token }: { token: Tokens.Code }) {
  return (
    <View style={styles.codeBlock}>
      {token.lang ? <Text style={styles.codeLang}>{token.lang}</Text> : null}
      <Text style={styles.codeText} selectable>
        {token.text}
      </Text>
    </View>
  );
}

function renderBlocks(
  tokens: Token[] | undefined,
  color: ColorValue,
): ReactNode[] {
  return (tokens ?? []).map((raw, index) => {
    const key = `${index}-${raw.type}`;
    if (isObjectCardToken(raw)) {
      return <ObjectCard key={key} spec={raw.spec} />;
    }
    const token = raw as MarkedToken;
    switch (token.type) {
      case "code":
        return isMermaidLang(token.lang) && isClosedFence(token.raw) ? (
          <MermaidDiagram
            key={key}
            code={token.text}
            fallback={<CodeBlock token={token} />}
          />
        ) : (
          <CodeBlock key={key} token={token} />
        );
      case "heading":
        return (
          <Text
            key={key}
            style={[
              styles.heading,
              {
                fontFamily: fonts.sans,
                fontSize: token.depth <= 2 ? 19 : 16,
                color,
              },
            ]}
          >
            {renderInline(token.tokens, color)}
          </Text>
        );
      case "list":
        return <List key={key} token={token} color={color} />;
      case "blockquote":
        return (
          <View key={key} style={styles.quote}>
            {renderBlocks(token.tokens, colors.inkSoft)}
          </View>
        );
      case "table":
        return <Table key={key} token={token} color={color} />;
      case "hr":
        return <View key={key} style={styles.rule} />;
      // Tight list items hold their text as a bare text token.
      case "paragraph":
      case "text":
        return (
          <Paragraph key={key} tokens={token.tokens ?? []} color={color} />
        );
      default:
        return null;
    }
  });
}

export function Markdown({ text, color = colors.ink }: MarkdownProps) {
  const tokens = useMemo(() => lexMarkdown(text), [text]);
  return <View style={styles.root}>{renderBlocks(tokens, color)}</View>;
}

const styles = StyleSheet.create({
  root: { gap: 8 },
  body: { fontFamily: fonts.sans, fontSize: 16, lineHeight: 24 },
  heading: { fontFamily: fonts.sansSemi, lineHeight: 26, marginTop: 4 },
  list: { gap: 4 },
  bulletRow: { flexDirection: "row", gap: 8, paddingLeft: 4 },
  bulletMark: {
    fontFamily: fonts.sans,
    fontSize: 16,
    lineHeight: 24,
    minWidth: 14,
  },
  bulletText: { flex: 1, gap: 4 },
  quote: {
    borderLeftWidth: 2,
    borderLeftColor: colors.line,
    paddingLeft: 12,
    gap: 8,
  },
  rule: { height: StyleSheet.hairlineWidth, backgroundColor: colors.line },
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
  strike: { textDecorationLine: "line-through" },
  runs: { gap: 8 },
  image: {
    width: "100%",
    borderRadius: 16,
    backgroundColor: colors.fill,
  },
  imagePending: { aspectRatio: 16 / 9 },
  link: { color: colors.accent, textDecorationLine: "underline" },
  chip: {
    fontFamily: fonts.sansMedium,
    color: colors.accent,
    backgroundColor: colors.fill,
  },
  table: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: 12,
    overflow: "hidden",
  },
  tableRow: { flexDirection: "row" },
  tableRowDivided: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  tableHeader: { backgroundColor: colors.fill },
  tableCell: {
    fontFamily: fonts.sans,
    fontSize: 14,
    lineHeight: 20,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  tableHeaderText: { fontFamily: fonts.sansSemi },
});
