import { EditorState } from "@codemirror/state";
import { EditorView, lineNumbers } from "@codemirror/view";
import { useMemo } from "react";
import { useThemeStore } from "../../../../shell/themeStore";
import { oneDark, oneLight } from "../../../code-editor/theme/editorTheme";
import { getLanguageExtension } from "../../../code-editor/utils/languages";

export function useCodePreviewExtensions(
  filePath: string | undefined,
  firstLineNumber = 1,
) {
  const isDarkMode = useThemeStore((state) => state.isDarkMode);

  return useMemo(() => {
    const languageExtension = filePath ? getLanguageExtension(filePath) : null;
    const theme = isDarkMode ? oneDark : oneLight;
    const compactPadding = EditorView.theme({
      ".cm-content": { padding: "0" },
    });

    return [
      theme,
      lineNumbers({ formatNumber: (n) => String(n + firstLineNumber - 1) }),
      EditorView.editable.of(false),
      EditorState.readOnly.of(true),
      EditorView.lineWrapping,
      ...(languageExtension ? [languageExtension] : []),
      compactPadding,
    ];
  }, [filePath, isDarkMode, firstLineNumber]);
}

export const CODE_PREVIEW_CONTAINER_STYLE: React.CSSProperties = {
  overflow: "hidden",
  "--color-background": "transparent",
} as React.CSSProperties;

export const CODE_PREVIEW_EDITOR_STYLE: React.CSSProperties = {
  fontSize: "12px",
  maxHeight: "750px",
  overflow: "auto",
};

export const CODE_PREVIEW_PATH_STYLE: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid var(--gray-a6)",
};
