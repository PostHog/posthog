import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { cn } from "@posthog/quill";
import { formatHogQL } from "@posthog/ui/features/canvas/formatHogQL";
import { useCodeMirror } from "@posthog/ui/features/code-editor/hooks/useCodeMirror";
import { useEditorExtensions } from "@posthog/ui/features/code-editor/hooks/useEditorExtensions";
import {
  type Ref,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";

export interface SqlEditorHandle {
  format: () => void;
}

interface SqlEditorProps {
  initialValue: string;
  onChange: (sql: string) => void;
  onRun: (sql: string) => void;
  className?: string;
  ref?: Ref<SqlEditorHandle>;
}

const sqlEditorTheme = EditorView.theme({
  "&": { maxHeight: "320px", fontSize: "12px", backgroundColor: "transparent" },
  ".cm-scroller": { overflow: "auto", lineHeight: "1.6" },
  ".cm-content": { color: "var(--gray-12)" },
  ".cm-content, .cm-gutter": { minHeight: "96px" },
  ".cm-gutters": {
    backgroundColor: "transparent",
    border: "none",
    color: "var(--gray-9)",
  },
  ".cm-activeLineGutter": { backgroundColor: "transparent" },
  ".cm-activeLine": { backgroundColor: "transparent" },
  "&.cm-focused": { outline: "none" },
});

const quietHighlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: tags.keyword, color: "var(--gray-12)", fontWeight: "600" },
    {
      tag: [tags.string, tags.special(tags.string)],
      color: "var(--accent-11)",
    },
    {
      tag: [
        tags.number,
        tags.name,
        tags.variableName,
        tags.propertyName,
        tags.typeName,
        tags.function(tags.variableName),
      ],
      color: "var(--gray-12)",
    },
    {
      tag: [tags.operator, tags.punctuation, tags.paren, tags.bracket],
      color: "var(--gray-11)",
    },
    { tag: tags.comment, color: "var(--gray-10)", fontStyle: "italic" },
  ]),
);

function replaceDoc(view: EditorView, next: string): void {
  const current = view.state.doc.toString();
  if (current === next) return;
  view.dispatch({
    changes: { from: 0, to: current.length, insert: next },
    selection: {
      anchor: Math.min(view.state.selection.main.head, next.length),
    },
  });
}

export function SqlEditor({
  initialValue,
  onChange,
  onRun,
  className,
  ref,
}: SqlEditorProps) {
  const base = useEditorExtensions("measure.sql");
  const docRef = useRef(formatHogQL(initialValue));
  const onChangeRef = useRef(onChange);
  const onRunRef = useRef(onRun);
  useEffect(() => {
    onChangeRef.current = onChange;
    onRunRef.current = onRun;
  }, [onChange, onRun]);
  useEffect(() => {
    if (docRef.current !== initialValue) onChangeRef.current(docRef.current);
  }, [initialValue]);

  const extensions = useMemo(
    () => [
      ...base,
      sqlEditorTheme,
      Prec.highest(quietHighlight),
      EditorView.updateListener.of((update) => {
        if (!update.docChanged) return;
        docRef.current = update.state.doc.toString();
        onChangeRef.current(docRef.current);
      }),
      Prec.highest(
        keymap.of([
          {
            key: "Mod-Enter",
            run: (view) => {
              replaceDoc(view, formatHogQL(view.state.doc.toString()));
              onRunRef.current(view.state.doc.toString());
              return true;
            },
          },
        ]),
      ),
    ],
    [base],
  );
  const options = useMemo(
    () => ({ doc: docRef.current, extensions }),
    [extensions],
  );
  const { containerRef, instanceRef } = useCodeMirror(options);

  useImperativeHandle(
    ref,
    () => ({
      format: () => {
        const view = instanceRef.current;
        if (view) replaceDoc(view, formatHogQL(view.state.doc.toString()));
      },
    }),
    [instanceRef],
  );

  return <div ref={containerRef} className={cn("min-w-0", className)} />;
}
