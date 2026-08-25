import { EditorView } from "@codemirror/view";
import {
  useDashboard,
  useDashboardMutations,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useEditorExtensions } from "@posthog/ui/features/code-editor/hooks/useEditorExtensions";
import { toast } from "@posthog/ui/primitives/toast";
import { useEffect, useRef, useState } from "react";

// The canvas side panel's markdown editor for the author-written context (the
// canvas record's `context`, passed to generation tasks). A self-contained
// CodeMirror instance (the shared CodeMirrorEditor is wired to the host
// workspace/context-menu, which the canvas panel must not touch), reusing the
// app's editor extensions + theme via useEditorExtensions. `context.md` drives
// markdown syntax highlighting.
const CONTEXT_FILE = "context.md";

/**
 * The author-context editor for a canvas, bound to the saved record: shows the
 * record's `context`, buffers edits locally while typing, and commits on blur
 * through the `saveContext` mutation (which invalidates the record so every
 * viewer converges on the saved text).
 */
export function CanvasContextEditor({ dashboardId }: { dashboardId: string }) {
  const { dashboard } = useDashboard(dashboardId);
  const { saveContext } = useDashboardMutations();
  const saved = dashboard?.context ?? "";

  // Local editing buffer; null = untouched (mirror the saved record). A
  // touched buffer stays authoritative — a record poll landing mid-edit must
  // not clobber unsaved typing — and resets only once the record catches up
  // with the committed text, so a commit can't flash the stale value while the
  // invalidated record refetches.
  const [draft, setDraft] = useState<string | null>(null);
  if (draft !== null && draft === saved) setDraft(null);

  const commit = () => {
    if (draft === null || draft === saved) return;
    saveContext(dashboardId, draft).catch((error: unknown) => {
      // The buffer stays authoritative, so the text isn't lost — the next
      // blur retries the save.
      toast.error("Couldn't save canvas context", {
        description: error instanceof Error ? error.message : String(error),
      });
    });
  };

  return (
    <ContextEditor
      key={dashboardId}
      value={draft ?? saved}
      onChange={setDraft}
      onCommit={commit}
    />
  );
}

export function ContextEditor({
  value,
  onChange,
  onCommit,
}: {
  value: string;
  /** Fires on every keystroke (live state). */
  onChange: (next: string) => void;
  /** Fires on blur — the moment to snapshot a version + autosave. */
  onCommit: () => void;
}) {
  const baseExtensions = useEditorExtensions(CONTEXT_FILE, false, false);
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  // Latest callbacks, read through a ref so the create-effect needn't depend on
  // them (which would tear down and rebuild the editor on every parent render).
  const cbRef = useRef({ onChange, onCommit });
  cbRef.current = { onChange, onCommit };
  // Latest value, so the create-effect seeds the right doc without listing
  // `value` as a dep (that would recreate the editor on every keystroke).
  const valueRef = useRef(value);
  valueRef.current = value;

  // (Re)create the editor when the extension set changes (e.g. theme toggle).
  useEffect(() => {
    if (!containerRef.current) return;
    const view = new EditorView({
      doc: valueRef.current,
      parent: containerRef.current,
      extensions: [
        ...baseExtensions,
        EditorView.updateListener.of((u) => {
          if (u.docChanged) cbRef.current.onChange(u.state.doc.toString());
        }),
        EditorView.domEventHandlers({
          blur: () => {
            cbRef.current.onCommit();
            return false;
          },
        }),
        EditorView.theme({
          "&": { height: "100%" },
          ".cm-scroller": { overflow: "auto" },
        }),
      ],
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, [baseExtensions]);

  // Sync EXTERNAL value changes (undo/redo, version switch, initial seed) into the
  // editor without clobbering the caret while the user is typing locally.
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: value },
      });
    }
  }, [value]);

  return <div ref={containerRef} className="h-full w-full overflow-hidden" />;
}
