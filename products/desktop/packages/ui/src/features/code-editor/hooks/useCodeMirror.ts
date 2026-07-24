import { EditorState, type Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useEffect, useRef } from "react";
import { useFileContextMenu } from "../../sessions/components/useFileContextMenu";

interface UseCodeMirrorOptions {
  doc: string;
  extensions: Extension[];
  filePath?: string;
}

export function useCodeMirror(options: UseCodeMirrorOptions) {
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<EditorView | null>(null);
  const { openForFile } = useFileContextMenu();
  const hostClient = useHostTRPCClient();

  useEffect(() => {
    if (!containerRef.current) return;

    instanceRef.current?.destroy();
    instanceRef.current = null;

    instanceRef.current = new EditorView({
      state: EditorState.create({
        doc: options.doc,
        extensions: options.extensions,
      }),
      parent: containerRef.current,
    });

    return () => {
      instanceRef.current?.destroy();
      instanceRef.current = null;
    };
  }, [options]);

  useEffect(() => {
    if (!instanceRef.current || !options.filePath) return;

    const filePath = options.filePath;
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
  }, [options.filePath, openForFile, hostClient]);

  return { containerRef, instanceRef };
}
