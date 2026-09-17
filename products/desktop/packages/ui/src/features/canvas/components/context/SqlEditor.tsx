import { Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
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
  ".cm-content, .cm-gutter": { minHeight: "96px" },
  ".cm-gutters": {
    backgroundColor: "transparent",
    border: "none",
    color: "var(--muted-foreground)",
    opacity: "0.7",
  },
  ".cm-activeLineGutter": { backgroundColor: "transparent" },
  ".cm-activeLine": { backgroundColor: "transparent" },
  "&.cm-focused": { outline: "none" },
});

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
