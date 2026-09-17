import { Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { cn } from "@posthog/quill";
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
  setValue: (sql: string) => void;
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
  ".cm-gutters": { backgroundColor: "transparent", border: "none" },
  ".cm-activeLineGutter": { backgroundColor: "transparent" },
  "&.cm-focused": { outline: "none" },
});

export function SqlEditor({
  initialValue,
  onChange,
  onRun,
  className,
  ref,
}: SqlEditorProps) {
  const base = useEditorExtensions("measure.sql");
  const docRef = useRef(initialValue);
  const onChangeRef = useRef(onChange);
  const onRunRef = useRef(onRun);
  useEffect(() => {
    onChangeRef.current = onChange;
    onRunRef.current = onRun;
  }, [onChange, onRun]);

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
      setValue: (sql: string) => {
        const view = instanceRef.current;
        if (!view) return;
        const current = view.state.doc.toString();
        if (current === sql) return;
        view.dispatch({
          changes: { from: 0, to: current.length, insert: sql },
          selection: {
            anchor: Math.min(view.state.selection.main.head, sql.length),
          },
        });
      },
    }),
    [instanceRef],
  );

  return <div ref={containerRef} className={cn("min-w-0", className)} />;
}
