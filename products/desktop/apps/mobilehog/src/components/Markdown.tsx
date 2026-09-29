import { isSafeExternalUrl } from "@posthog/shared";
import { type MarkedToken, marked, type Token, type Tokens } from "marked";
import { type ReactNode, useMemo } from "react";
import {
  type ColorValue,
  Linking,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { colors, fonts } from "@/lib/theme";

interface MarkdownProps {
  text: string;
  color?: ColorValue;
}

function openLink(href: string): void {
  if (isSafeExternalUrl(href)) Linking.openURL(href).catch(() => {});
}

function renderInline(
  tokens: Token[] | undefined,
  color: ColorValue,
): ReactNode[] {
  return (tokens ?? []).map((raw, index) => {
    const token = raw as MarkedToken;
    const key = String(index);
    switch (token.type) {
      case "strong":
        return (
          <Text key={key} style={{ fontFamily: fonts.sansSemi, color }}>
            {renderInline(token.tokens, color)}
          </Text>
        );
      case "em":
        return (
          <Text key={key} style={{ fontFamily: fonts.sansItalic, color }}>
            {renderInline(token.tokens, color)}
          </Text>
        );
      case "del":
        return (
          <Text key={key} style={styles.strike}>
            {renderInline(token.tokens, color)}
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
            {renderInline(token.tokens, colors.accent)}
          </Text>
        );
      case "br":
        return "\n";
      case "text":
        return token.tokens ? (
          <Text key={key}>{renderInline(token.tokens, color)}</Text>
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

function renderBlocks(
  tokens: Token[] | undefined,
  color: ColorValue,
): ReactNode[] {
  return (tokens ?? []).map((raw, index) => {
    const token = raw as MarkedToken;
    const key = `${index}-${token.type}`;
    switch (token.type) {
      case "code":
        return (
          <View key={key} style={styles.codeBlock}>
            {token.lang ? (
              <Text style={styles.codeLang}>{token.lang}</Text>
            ) : null}
            <Text style={styles.codeText} selectable>
              {token.text}
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
          <Text key={key} style={[styles.body, { color }]} selectable>
            {renderInline(token.tokens, color)}
          </Text>
        );
      default:
        return null;
    }
  });
}

export function Markdown({ text, color = colors.ink }: MarkdownProps) {
  const tokens = useMemo(() => marked.lexer(text), [text]);
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
  link: { color: colors.accent, textDecorationLine: "underline" },
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
