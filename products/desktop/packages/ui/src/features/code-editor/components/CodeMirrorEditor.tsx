import { openSearchPanel } from "@codemirror/search";
import { RangeSetBuilder, StateField } from "@codemirror/state";
import { Decoration, type DecorationSet, EditorView } from "@codemirror/view";
import type { SerializedEnrichment } from "@posthog/shared";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useEffect, useMemo, useRef } from "react";
import { setEnrichmentEffect } from "../extensions/postHogEnrichment";
import { useCodeMirror } from "../hooks/useCodeMirror";
import { useEditorExtensions } from "../hooks/useEditorExtensions";
import { usePendingScrollStore } from "../pendingScrollStore";

const selectedLineDecoration = Decoration.line({ class: "cm-selected-lines" });
const selectedLinesField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(_value, tr) {
    const sel = tr.state.selection.main;
    if (sel.empty) return Decoration.none;
    const builder = new RangeSetBuilder<Decoration>();
    const from = tr.state.doc.lineAt(sel.from).number;
    const to = tr.state.doc.lineAt(sel.to).number;
    for (let n = from; n <= to; n++) {
      const pos = tr.state.doc.line(n).from;
      builder.add(pos, pos, selectedLineDecoration);
    }
    return builder.finish();
  },
  provide: (f) => EditorView.decorations.from(f),
});
const selectedLinesTheme = EditorView.theme({
  ".cm-selected-lines": {
    backgroundColor: "var(--accent-a3)",
    boxShadow: "inset 2px 0 0 0 var(--accent-8)",
  },
  "& .cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    background: "transparent !important",
  },
});

export interface EditorSelection {
  text: string;
  /** 1-based line numbers. */
  fromLine: number;
  toLine: number;
  /** Viewport position of the selection's end caret, or null when off-screen. */
  anchor: { top: number; endX: number; bottom: number } | null;
}

interface CodeMirrorEditorProps {
  content: string;
  filePath?: string;
  relativePath?: string;
  readOnly?: boolean;
  enrichment?: SerializedEnrichment | null;
  /** Fires on every selection (or doc) change with the current selection. */
  onSelectionChange?: (selection: EditorSelection) => void;
  onContentChange?: (content: string) => void;
  /** Highlight the active selection as full lines (code-review style). */
  highlightSelectedLines?: boolean;
}

export function CodeMirrorEditor({
  content,
  filePath,
  relativePath,
  readOnly = false,
  enrichment,
  onSelectionChange,
  onContentChange,
  highlightSelectedLines = false,
}: CodeMirrorEditorProps) {
  const enrichmentEnabled = enrichment !== undefined;
  const baseExtensions = useEditorExtensions(
    filePath,
    readOnly,
    enrichmentEnabled,
  );

  // Ref-stable listener: a changing extension would tear down the editor.
  const onSelectionChangeRef = useRef(onSelectionChange);
  useEffect(() => {
    onSelectionChangeRef.current = onSelectionChange;
  }, [onSelectionChange]);
  const onContentChangeRef = useRef(onContentChange);
  useEffect(() => {
    onContentChangeRef.current = onContentChange;
  }, [onContentChange]);
  const selectionExtension = useMemo(
    () =>
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          onContentChangeRef.current?.(update.state.doc.toString());
        }
        const cb = onSelectionChangeRef.current;
        if (!cb) return;
        const changed = update.selectionSet || update.docChanged;
        // Also refire on scroll/resize so the anchor tracks the selection.
        const moved = update.viewportChanged || update.geometryChanged;
        if (!changed && !moved) return;
        const sel = update.state.selection.main;
        const doc = update.state.doc;
        if (sel.empty) {
          // No coords for an empty caret — just notify so consumers can hide.
          if (changed) {
            cb({
              text: "",
              fromLine: doc.lineAt(sel.from).number,
              toLine: doc.lineAt(sel.to).number,
              anchor: null,
            });
          }
          return;
        }
        const endRect = update.view.coordsAtPos(sel.to);
        cb({
          text: doc.sliceString(sel.from, sel.to),
          fromLine: doc.lineAt(sel.from).number,
          toLine: doc.lineAt(sel.to).number,
          anchor: endRect
            ? {
                top: endRect.top,
                endX: endRect.right,
                bottom: endRect.bottom,
              }
            : null,
        });
      }),
    [],
  );
  const extensions = useMemo(
    () => [
      ...baseExtensions,
      selectionExtension,
      ...(highlightSelectedLines
        ? [selectedLinesField, selectedLinesTheme]
        : []),
    ],
    [baseExtensions, selectionExtension, highlightSelectedLines],
  );

  const options = useMemo(
    () => ({ doc: content, extensions, filePath }),
    [content, extensions, filePath],
  );
  const { containerRef, instanceRef } = useCodeMirror(options);

  useEffect(() => {
    if (!enrichmentEnabled) return;
    const view = instanceRef.current;
    if (!view) return;
    view.dispatch({
      effects: setEnrichmentEffect.of(enrichment ?? null),
    });
  }, [enrichment, enrichmentEnabled, instanceRef]);

  useEffect(() => {
    if (!filePath) return;
    const scrollToLine = () => {
      const line = usePendingScrollStore.getState().pendingLine[filePath];
      if (line === undefined) return;
      const view = instanceRef.current;
      if (!view) return;
      usePendingScrollStore.getState().consumeScroll(filePath);
      const lineCount = view.state.doc.lines;
      if (line < 1 || line > lineCount) return;
      const lineInfo = view.state.doc.line(line);
      view.dispatch({
        selection: { anchor: lineInfo.from },
        effects: EditorView.scrollIntoView(lineInfo.from, { y: "center" }),
      });
    };
    const rafId = requestAnimationFrame(scrollToLine);
    const unsub = usePendingScrollStore.subscribe(scrollToLine);
    return () => {
      cancelAnimationFrame(rafId);
      unsub();
    };
  }, [filePath, instanceRef]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key !== "f") return;

      const instance = instanceRef.current;
      if (!instance || !(instance instanceof EditorView)) return;

      e.preventDefault();
      e.stopPropagation();
      openSearchPanel(instance);
    };

    document.addEventListener("keydown", handleKeyDown, { capture: true });
    return () =>
      document.removeEventListener("keydown", handleKeyDown, { capture: true });
  }, [instanceRef]);

  if (!relativePath) {
    return <div ref={containerRef} className="h-full w-full" />;
  }

  return (
    <Flex direction="column" height="100%">
      <Box px="3" py="2" className="shrink-0 border-b border-b-(--gray-6)">
        <Text
          color="gray"
          className="font-[var(--code-font-family)] text-[13px]"
        >
          {relativePath}
        </Text>
      </Box>
      <Box className="flex-1 overflow-auto">
        <div ref={containerRef} className="h-full w-full" />
      </Box>
    </Flex>
  );
}
