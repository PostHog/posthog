import { Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { cn } from "@posthog/quill";
import { useCodeMirror } from "@posthog/ui/features/code-editor/hooks/useCodeMirror";
import { useEditorExtensions } from "@posthog/ui/features/code-editor/hooks/useEditorExtensions";
import { useEffect, useMemo, useRef } from "react";

interface SqlEditorProps {
  initialValue: string;
  onChange: (sql: string) => void;
  onRun: (sql: string) => void;
  className?: string;
}

const sqlEditorTheme = EditorView.theme({
  "&": { height: "100%", fontSize: "12px", backgroundColor: "transparent" },
  ".cm-scroller": { overflow: "auto", lineHeight: "1.6" },
  ".cm-gutters": { backgroundColor: "transparent", border: "none" },
  "&.cm-focused": { outline: "none" },
});

export function SqlEditor({
  initialValue,
  onChange,
  onRun,
  className,
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
  const { containerRef } = useCodeMirror(options);

  return <div ref={containerRef} className={cn("min-w-0", className)} />;
}
