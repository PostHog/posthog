import "./blocks.css";
import { CANVAS_ENTRY_PATH } from "@posthog/core/canvas/blockLibrary/blockProject";
import { parseParamSchema } from "@posthog/core/canvas/blockLibrary/params";
import type { SourceRange } from "@posthog/core/canvas/blockLibrary/sourceEdits";
import {
  type CanvasNavIntent,
  canvasToHostMessageSchema,
} from "@posthog/core/canvas/freeformSchemas";
import {
  type CanvasEditSelection,
  useCanvasSourceEntry,
  useCanvasSourceStore,
} from "@posthog/ui/features/canvas/blocks/canvasSourceStore";
import {
  CANVAS_EDITOR_CHANNEL,
  postToCanvasEditor,
} from "@posthog/ui/features/canvas/blocks/editorFrame";
import { SourceDragOverlay } from "@posthog/ui/features/canvas/blocks/SourceDragOverlay";
import {
  activeSourceDrag,
  beginSourceDrag,
  type SourceDropHit,
} from "@posthog/ui/features/canvas/blocks/sourceDrag";
import { useCanvasSourceActions } from "@posthog/ui/features/canvas/blocks/useCanvasSourceActions";
import { createCanvasHostMessageRouter } from "@posthog/ui/features/canvas/freeform/canvasHostMessageRouter";
import { buildSandboxDocument } from "@posthog/ui/features/canvas/freeform/sandboxRuntime";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";

interface EditElementMessage extends Omit<CanvasEditSelection, "params"> {
  params: string | null;
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

function toSelection(
  element: EditElementMessage | null,
): CanvasEditSelection | null {
  return element
    ? { ...element, params: parseParamSchema(element.params) }
    : null;
}

export function CanvasSourceEditor({
  canvasId,
  onDataRequest,
  onError,
  onRendered,
  onNavigate,
}: {
  canvasId: string;
  onDataRequest: (method: string, payload: unknown) => Promise<unknown>;
  onError?: (message: string, stack?: string) => void;
  onRendered?: () => void;
  onNavigate?: (intent: CanvasNavIntent) => void;
}) {
  const entry = useCanvasSourceEntry(canvasId);
  const actions = useCanvasSourceActions(canvasId);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const readyRef = useRef(false);
  const theme = useThemeStore((state) => (state.isDarkMode ? "dark" : "light"));
  const srcDoc = useMemo(() => buildSandboxDocument(), []);
  const latest = useRef({
    onDataRequest,
    onError,
    onRendered,
    onNavigate,
    theme,
    actions,
  });
  useLayoutEffect(() => {
    latest.current = {
      onDataRequest,
      onError,
      onRendered,
      onNavigate,
      theme,
      actions,
    };
  });

  const sendInit = useCallback(() => {
    const snapshot = useCanvasSourceStore.getState().entries[canvasId];
    if (!snapshot || !readyRef.current) return;
    postToCanvasEditor({
      type: "init",
      files: snapshot.files,
      entry: CANVAS_ENTRY_PATH,
      editing: true,
      rev: snapshot.rev,
      focusBlockId: snapshot.focusBlockId,
      focusSource: snapshot.focusSource,
      theme: latest.current.theme,
      highlights: [],
    });
  }, [canvasId]);

  const rev = entry?.rev;
  useEffect(() => {
    if (rev !== undefined) sendInit();
  }, [rev, sendInit]);

  useEffect(() => {
    postToCanvasEditor({ type: "set-theme", theme });
  }, [theme]);

  const handleEdit = useCallback(
    (data: Record<string, unknown>) => {
      const store = useCanvasSourceStore.getState();
      const frameRect = iframeRef.current?.getBoundingClientRect();
      const offsetX = frameRect?.left ?? 0;
      const offsetY = frameRect?.top ?? 0;
      switch (data.type) {
        case "canvas-edit-select":
          if (data.byPointer === true) store.setLibraryOpen(canvasId, false);
          latest.current.actions.select(
            toSelection((data.element as EditElementMessage | null) ?? null),
          );
          return;
        case "canvas-edit-root":
          store.setMounted(
            canvasId,
            Number(data.rev),
            (data.root as SourceRange | null) ?? null,
          );
          return;
        case "canvas-edit-drop-target":
          activeSourceDrag()?.hit((data.hit as SourceDropHit | null) ?? null);
          return;
        case "canvas-edit-drag-start": {
          const element = toSelection(data.element as EditElementMessage);
          if (!element) return;
          beginSourceDrag({
            source: { kind: "move", selection: element },
            startX: offsetX + Number(data.x),
            startY: offsetY + Number(data.y),
            onDrop: latest.current.actions.drop,
          });
          return;
        }
        case "canvas-edit-pointer":
          activeSourceDrag()?.move(
            offsetX + Number(data.x),
            offsetY + Number(data.y),
          );
          return;
        case "canvas-edit-pointer-up":
          activeSourceDrag()?.end(true);
          return;
        case "canvas-edit-pointer-cancel":
          activeSourceDrag()?.end(false);
          return;
        case "canvas-edit-key":
          handleKey(canvasId, data, latest.current.actions);
          return;
        case "canvas-edit-text": {
          const element = toSelection(data.element as EditElementMessage);
          if (element && typeof data.text === "string")
            latest.current.actions.setText(element, data.text);
          return;
        }
      }
    },
    [canvasId],
  );

  useLayoutEffect(() => {
    const route = createCanvasHostMessageRouter({
      post: (message) =>
        iframeRef.current?.contentWindow?.postMessage(message, "*"),
      callbacks: () => ({
        onReady: () => {
          readyRef.current = true;
          sendInit();
        },
        onDataRequest: latest.current.onDataRequest,
        onError: (message, stack) => latest.current.onError?.(message, stack),
        onRendered: () => latest.current.onRendered?.(),
        onNavigate: (intent) => latest.current.onNavigate?.(intent),
        onTextSelection: () => undefined,
        onCommentActivate: () => undefined,
      }),
      hasUserActivation: () => navigator.userActivation?.isActive === true,
      openExternal: openExternalUrl,
      onExternalOpenBlocked: () => undefined,
    });
    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as Record<string, unknown> | null;
      if (!data || data.channel !== CANVAS_EDITOR_CHANNEL) return;
      if (
        typeof data.type === "string" &&
        data.type.startsWith("canvas-edit-")
      ) {
        handleEdit(data);
        return;
      }
      const parsed = canvasToHostMessageSchema.safeParse(data);
      if (parsed.success) void route(parsed.data);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [handleEdit, sendInit]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      const shortcut = event.metaKey || event.ctrlKey;
      if (!shortcut && event.target !== document.body) return;
      handleKey(
        canvasId,
        {
          key: event.key,
          metaKey: event.metaKey,
          ctrlKey: event.ctrlKey,
          shiftKey: event.shiftKey,
        },
        latest.current.actions,
        () => event.preventDefault(),
      );
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canvasId]);

  return (
    <div className="relative h-full w-full">
      <iframe
        ref={iframeRef}
        title="Canvas editor"
        data-canvas-source-editor=""
        srcDoc={srcDoc}
        sandbox="allow-scripts"
        className="h-full w-full border-0 bg-transparent"
      />
      <SourceDragOverlay />
    </div>
  );
}

function handleKey(
  canvasId: string,
  data: Record<string, unknown>,
  actions: ReturnType<typeof useCanvasSourceActions>,
  prevent?: () => void,
): void {
  const store = useCanvasSourceStore.getState();
  const selection = store.selection[canvasId] ?? null;
  const key = String(data.key ?? "");
  const mod = data.metaKey === true || data.ctrlKey === true;
  if (key === "Escape") {
    const drag = activeSourceDrag();
    if (drag) drag.end(false);
    else {
      actions.select(null);
      postToCanvasEditor({ type: "canvas-edit-deselect" });
    }
    return;
  }
  if (mod && key.toLowerCase() === "z") {
    prevent?.();
    if (data.shiftKey === true) store.redo(canvasId);
    else store.undo(canvasId);
    return;
  }
  if (!selection) return;
  if (key === "Backspace" || key === "Delete") {
    prevent?.();
    actions.remove(selection);
    return;
  }
  if (mod && key.toLowerCase() === "d") {
    prevent?.();
    actions.duplicate(selection);
  }
}
