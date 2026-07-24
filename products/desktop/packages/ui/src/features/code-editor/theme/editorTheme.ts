import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import type { Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";

function withAlpha(hex: string, alpha: number): string {
  const a = Math.round(alpha * 255)
    .toString(16)
    .padStart(2, "0");
  return `${hex}${a}`;
}

// PostHog-inspired dark theme colors
const dark = {
  chalky: "#e5c07b",
  coral: "#e06c75",
  cyan: "#56b6c2",
  invalid: "#e6e6e6",
  ivory: "#e6e6e6",
  stone: "#9898b6",
  malibu: "#61afef",
  sage: "#98c379",
  whiskey: "#d19a66",
  violet: "#c678dd",
  background: "#131316",
  highlightBackground: "#1e1e28",
  tooltipBackground: "#24243e",
  selection: "#2e2e3d",
  cursor: "#f8be2a",
};

// PostHog-inspired light theme colors
const light = {
  chalky: "#c18401",
  coral: "#c45649",
  cyan: "#0184bc",
  invalid: "#0d0d0d",
  ivory: "#1a1d17",
  stone: "#6b7165",
  malibu: "#4078f2",
  sage: "#50a14f",
  whiskey: "#986801",
  violet: "#a626a4",
  background: "#f2f3ee",
  highlightBackground: "#e4e5de",
  tooltipBackground: "#eceee8",
  selection: "#d8dbd1",
  cursor: "#f54d00",
};

function createEditorTheme(colors: typeof dark, isDark: boolean) {
  return EditorView.theme(
    {
      "&": {
        height: "100%",
        fontSize: "13px",
        color: colors.ivory,
        backgroundColor: "var(--color-background)",
      },
      ".cm-scroller": {
        overflow: "auto",
        fontFamily: "var(--code-font-family)",
      },
      ".cm-content": {
        caretColor: colors.cursor,
      },
      "&:not(.cm-merge-a):not(.cm-merge-b) .cm-content": {
        padding: "16px 0",
      },
      ".cm-line": {
        padding: "0 16px",
      },
      ".cm-cursor, .cm-dropCursor": {
        borderLeftColor: colors.cursor,
      },
      "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection":
        {
          backgroundColor: colors.selection,
        },
      ".cm-panels": {
        backgroundColor: colors.background,
        color: colors.ivory,
      },
      ".cm-panels.cm-panels-top": {
        borderBottom: `1px solid ${colors.selection}`,
      },
      ".cm-panels.cm-panels-bottom": {
        borderTop: `1px solid ${colors.selection}`,
      },
      ".cm-panel.cm-search": {
        padding: "6px 8px",
        fontSize: "12px",
        gap: "4px",
        "& input[name=replace]": {
          display: "none",
        },
        "& button[name=replace]": {
          display: "none",
        },
        "& button[name=replaceAll]": {
          display: "none",
        },
        "& input": {
          background: colors.highlightBackground,
          color: colors.ivory,
          border: `1px solid ${colors.selection}`,
          borderRadius: "3px",
          padding: "2px 6px",
          fontSize: "12px",
          outline: "none",
          "&:focus": {
            borderColor: colors.malibu,
          },
        },
        "& button": {
          background: colors.highlightBackground,
          color: colors.ivory,
          border: `1px solid ${colors.selection}`,
          borderRadius: "3px",
          padding: "2px 8px",
          fontSize: "11px",
          cursor: "pointer",
          "&:hover": {
            background: colors.selection,
          },
        },
        "& label": {
          fontSize: "11px",
          color: colors.stone,
        },
        "& .cm-button": {
          backgroundImage: "none",
        },
      },
      ".cm-searchMatch": {
        backgroundColor: withAlpha(colors.malibu, 0.35),
        outline: `1px solid ${colors.malibu}`,
      },
      ".cm-searchMatch.cm-searchMatch-selected": {
        backgroundColor: withAlpha(colors.malibu, 0.2),
      },
      ".cm-activeLine": {
        backgroundColor: withAlpha(colors.malibu, 0.04),
      },
      ".cm-selectionMatch": {
        backgroundColor: withAlpha(colors.sage, 0.1),
      },
      "&.cm-focused .cm-matchingBracket, &.cm-focused .cm-nonmatchingBracket": {
        backgroundColor: withAlpha(colors.malibu, 0.3),
      },
      ".cm-gutters": {
        backgroundColor: "var(--color-background)",
        color: colors.stone,
        border: "none",
      },
      ".cm-activeLineGutter": {
        backgroundColor: colors.highlightBackground,
      },
      ".cm-foldPlaceholder": {
        backgroundColor: "transparent",
        border: "none",
        color: colors.stone,
      },
      ".cm-tooltip": {
        border: "none",
        backgroundColor: colors.tooltipBackground,
      },
      ".cm-tooltip .cm-tooltip-arrow:before": {
        borderTopColor: "transparent",
        borderBottomColor: "transparent",
      },
      ".cm-tooltip .cm-tooltip-arrow:after": {
        borderTopColor: colors.tooltipBackground,
        borderBottomColor: colors.tooltipBackground,
      },
      ".cm-tooltip-autocomplete": {
        "& > ul > li[aria-selected]": {
          backgroundColor: colors.highlightBackground,
          color: colors.ivory,
        },
      },
    },
    { dark: isDark },
  );
}

function createHighlightStyle(colors: typeof dark) {
  return HighlightStyle.define([
    { tag: t.keyword, color: colors.violet },
    {
      tag: [t.name, t.deleted, t.character, t.propertyName, t.macroName],
      color: colors.coral,
    },
    { tag: [t.function(t.variableName), t.labelName], color: colors.malibu },
    {
      tag: [t.color, t.constant(t.name), t.standard(t.name)],
      color: colors.whiskey,
    },
    { tag: [t.definition(t.name), t.separator], color: colors.ivory },
    {
      tag: [
        t.typeName,
        t.className,
        t.number,
        t.changed,
        t.annotation,
        t.modifier,
        t.self,
        t.namespace,
      ],
      color: colors.chalky,
    },
    {
      tag: [
        t.operator,
        t.operatorKeyword,
        t.url,
        t.escape,
        t.regexp,
        t.link,
        t.special(t.string),
      ],
      color: colors.cyan,
    },
    { tag: [t.meta, t.comment], color: colors.stone },
    { tag: t.strong, fontWeight: "bold" },
    { tag: t.emphasis, fontStyle: "italic" },
    { tag: t.strikethrough, textDecoration: "line-through" },
    { tag: t.link, color: colors.stone, textDecoration: "underline" },
    { tag: t.heading, fontWeight: "bold", color: colors.coral },
    { tag: [t.atom, t.bool, t.special(t.variableName)], color: colors.whiskey },
    {
      tag: [t.processingInstruction, t.string, t.inserted],
      color: colors.sage,
    },
    { tag: t.invalid, color: colors.invalid },
  ]);
}

export const oneDark: Extension = [
  createEditorTheme(dark, true),
  syntaxHighlighting(createHighlightStyle(dark)),
];

export const oneLight: Extension = [
  createEditorTheme(light, false),
  syntaxHighlighting(createHighlightStyle(light)),
];
