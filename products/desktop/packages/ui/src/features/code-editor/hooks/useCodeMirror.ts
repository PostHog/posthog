import { Compartment, EditorState, type Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useEffect, useRef } from "react";
import { useFileContextMenu } from "../../sessions/components/useFileContextMenu";

interface UseCodeMirrorOptions {
  doc: string;
  extensions: Extension[];
  filePath?: string;
}

/**
 * One EditorView for the life of the container. Extensions swap through a
 * compartment and an outside document change lands as a transaction, so a
 * consumer that mirrors edits into React state never rebuilds the editor or
 * loses the caret on a keystroke.
 */
export function useCodeMirror(options: UseCodeMirrorOptions) {
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<EditorView | null>(null);
  const compartmentRef = useRef(new Compartment());
  const latestRef = useRef(options);
  latestRef.current = options;
  const { openForFile } = useFileContextMenu();
  const hostClient = useHostTRPCClient();
  const { doc, extensions, filePath } = options;

  useEffect(() => {
    const parent = containerRef.current;
    if (!parent) return;
    const initial = latestRef.current;
    const view = new EditorView({
      state: EditorState.create({
        doc: initial.doc,
        extensions: compartmentRef.current.of(initial.extensions),
      }),
      parent,
    });
    instanceRef.current = view;
    return () => {
      view.destroy();
      instanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    const view = instanceRef.current;
    if (!view) return;
    view.dispatch({
      effects: compartmentRef.current.reconfigure(extensions),
    });
  }, [extensions]);

  useEffect(() => {
    const view = instanceRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === doc) return;
    view.dispatch({
      changes: { from: 0, to: current.length, insert: doc },
      selection: {
        anchor: Math.min(view.state.selection.main.head, doc.length),
      },
    });
  }, [doc]);

  useEffect(() => {
    const view = instanceRef.current;
    if (!view || !filePath) return;
    view.dispatch({
      selection: { anchor: 0 },
      effects: EditorView.scrollIntoView(0),
    });
  }, [filePath]);

  useEffect(() => {
    if (!instanceRef.current || !filePath) return;

    const domElement = instanceRef.current.dom;

    const handleContextMenu = async (e: MouseEvent) => {
      e.preventDefault();

      const filename = filePath.split("/").pop() || "file";
      const workspaces = await hostClient.workspace.getAll.query();
      const workspace =
        Object.values(workspaces).find(
          (ws) =>
            (ws?.worktreePath && filePath.startsWith(ws.worktreePath)) ||
            (ws?.folderPath && filePath.startsWith(ws.folderPath)),
        ) ?? null;

      await openForFile({
        absolutePath: filePath,
        filename,
        workspace,
        mainRepoPath: workspace?.folderPath,
      });
    };

    domElement.addEventListener("contextmenu", handleContextMenu);

    return () => {
      domElement.removeEventListener("contextmenu", handleContextMenu);
    };
  }, [filePath, openForFile, hostClient]);

  return { containerRef, instanceRef };
}
