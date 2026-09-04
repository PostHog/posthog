import {
  ArrowLeftIcon,
  LinkIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import {
  BOARD_FIT_MAX_ZOOM,
  boardBounds,
  clampViewport,
  clampZoom,
  fitToContent,
  zoomAroundCenter,
  zoomTo,
} from "@posthog/core/canvas-v2/boardGeometry";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Skeleton,
} from "@posthog/quill";
import type { CanvasV2Fragment, CanvasV2Op } from "@posthog/shared";
import {
  CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT,
  CANVAS_V2_FRAGMENT_DEFAULT_WIDTH,
  findFreeSpot,
  maxZ,
  minZ,
} from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useCanvasViewedStore } from "@posthog/ui/features/canvas/stores/canvasViewedStore";
import { copyCanvasLink } from "@posthog/ui/features/canvas/utils/copyCanvasLink";
import {
  BACK_TO_CANVASES_ACTION,
  BOARD_LOAD_ERROR_DESCRIPTION,
  BOARD_LOAD_ERROR_TITLE,
  COPY_BOARD_LINK_ACTION,
  DEFAULT_BOARD_NAME,
  RENAME_BOARD_ACTION,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { useApplyBoardToolCalls } from "@posthog/ui/features/canvas-v2/hooks/useApplyBoardToolCalls";
import { useBoardApi } from "@posthog/ui/features/canvas-v2/hooks/useBoardApi";
import { useBoardCache } from "@posthog/ui/features/canvas-v2/hooks/useBoardCache";
import { useBoardKeyboard } from "@posthog/ui/features/canvas-v2/hooks/useBoardKeyboard";
import {
  useBoardTaskId,
  useBoardViewport,
  useBoardViewportStore,
} from "@posthog/ui/features/canvas-v2/hooks/useBoardViewportStore";
import { useCanvasV2BoardMutations } from "@posthog/ui/features/canvas-v2/hooks/useCanvasV2BoardMutations";
import {
  selectBoardFragment,
  useBoardViewStore,
} from "@posthog/ui/features/canvas-v2/interaction/boardViewStore";
import { libraryEntry } from "@posthog/ui/features/canvas-v2/library/registry";
import { useBoardPeers } from "@posthog/ui/features/canvas-v2/presence/useBoardPeers";
import { useBoardStream } from "@posthog/ui/features/canvas-v2/presence/useBoardStream";
import { usePresenceSender } from "@posthog/ui/features/canvas-v2/presence/usePresenceSender";
import { useBoardSync } from "@posthog/ui/features/canvas-v2/sync/useBoardSync";
import { HeaderTitleEditor } from "@posthog/ui/features/task-detail/HeaderTitleEditor";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToCanvases,
  navigateToSpaceCanvases,
} from "@posthog/ui/router/navigationBridge";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useQueryClient } from "@tanstack/react-query";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { readPaneRect } from "../interaction/useBoardPointer";
import { buildLastEdits } from "../lastEdits";
import { BoardChatPanel } from "./BoardChatPanel";
import { BoardEmptyHero } from "./BoardEmptyHero";
import { BoardMinimap } from "./BoardMinimap";
import { BoardStage } from "./BoardStage";
import { BoardToolbar } from "./BoardToolbar";
import { EditFragmentDialog } from "./EditFragmentDialog";
import type { FragmentLastEdit } from "./FragmentOverlay";
import { HistoryPanel } from "./HistoryPanel";
import { LibraryPalette } from "./LibraryPalette";
import { PresenceFaces } from "./PresenceFaces";
import { StateInspector } from "./StateInspector";
import { SyncChip } from "./SyncChip";

const EMPTY_PANE = { left: 0, top: 0, width: 0, height: 0 };

/** One board: the stage, its chrome, and the side panels. */
export function BoardView({
  boardId,
  channelId,
}: {
  boardId: string;
  channelId?: string;
}): ReactElement {
  const paneRef = useRef<HTMLDivElement | null>(null);
  const queryClient = useQueryClient();
  const api = useBoardApi();
  const authClient = useOptionalAuthenticatedClient();
  const currentUser = useCurrentUser({ client: authClient });
  const theme = useThemeStore((s) => (s.isDarkMode ? "dark" : "light"));
  const actorUser = useMemo(
    () =>
      currentUser.data
        ? {
            userId: currentUser.data.id,
            userName: currentUser.data.first_name || currentUser.data.email,
          }
        : undefined,
    [currentUser.data],
  );
  const { state, client } = useBoardSync(boardId, api, actorUser);

  useBoardCache(boardId, state);

  const presence = usePresenceSender(boardId);
  const { peers, ingest } = useBoardPeers(presence.clientId);
  useBoardStream(boardId, {
    onOp: (entry) => client?.ingestStreamEntry(entry),
    onPresence: ingest,
    onReload: () => void client?.poll(),
    onLive: (live) => client?.setLive(live),
  });

  const viewport = useBoardViewport(boardId);
  const setViewportForBoard = useBoardViewportStore((s) => s.setViewport);
  const fragments = state.snapshot.fragments;
  const setViewport = useCallback(
    (next: typeof viewport) => {
      const rect = readPaneRect(paneRef.current);
      setViewportForBoard(
        boardId,
        rect
          ? clampViewport(
              next,
              { w: rect.width, h: rect.height },
              boardBounds(fragments),
            )
          : next,
      );
    },
    [boardId, fragments, setViewportForBoard],
  );
  const taskId = useBoardTaskId(boardId);

  const view = useBoardViewStore();
  // One side panel at a time: they share one column.
  const openOnly = useCallback(
    (panel: "palette" | "chat" | "history" | "inspector" | null) => {
      view.setPaletteOpen(panel === "palette");
      view.setChatOpen(panel === "chat");
      view.setHistoryOpen(panel === "history");
      view.setInspectorOpen(panel === "inspector");
    },
    [view],
  );
  const togglePanel = useCallback(
    (panel: "palette" | "chat" | "history" | "inspector", open: boolean) =>
      openOnly(open ? null : panel),
    [openOnly],
  );
  const markCanvasViewed = useCanvasViewedStore(
    (viewed) => viewed.markCanvasViewed,
  );
  useEffect(() => {
    markCanvasViewed(boardId, Date.now());
  }, [boardId, markCanvasViewed]);
  const shareChannelId = channelId ?? state.channelId;
  const [renaming, setRenaming] = useState(false);
  const { renameBoard, isRenaming } = useCanvasV2BoardMutations();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const applyLocal = useCallback(
    (ops: CanvasV2Op[], opIds?: string[]) =>
      client?.applyLocal(ops, undefined, opIds),
    [client],
  );

  const addFromLibrary = useCallback(
    (name: string, world?: { x: number; y: number }) => {
      const entry = libraryEntry(name);
      if (!entry || !client) return;
      const snapshot = client.getState().snapshot;
      const size = entry.defaultSize ?? {
        w: CANVAS_V2_FRAGMENT_DEFAULT_WIDTH,
        h: CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT,
      };
      const spot = world ?? findFreeSpot(snapshot, size.w, size.h);
      const fragment: CanvasV2Fragment = {
        id: `${entry.name}-${globalThis.crypto.randomUUID()}`,
        title: entry.label,
        x: Math.round(spot.x),
        y: Math.round(spot.y),
        w: size.w,
        h: size.h,
        z: entry.layer === "back" ? minZ(snapshot) - 1 : maxZ(snapshot) + 1,
        code: entry.code,
        codeVersion: 1,
        ...(entry.surface ? { surface: entry.surface } : {}),
      };
      client.applyLocal([{ type: "add_fragment", fragment }]);
      view.setSelection([fragment.id]);
    },
    [client, view],
  );

  useApplyBoardToolCalls(client, taskId, selectBoardFragment);

  useBoardKeyboard({
    enabled: editingId === null && view.focusedId === null,
    paneRef,
    fragments: state.snapshot.fragments,
    viewport,
    setViewport,
    selectedIds: view.selectedIds,
    onDeleteSelected: (ids) => {
      applyLocal(ids.map((id) => ({ type: "remove_fragment", id })));
      view.clearSelection();
    },
    onClearSelection: () => view.clearSelection(),
    onSelectAll: () =>
      view.setSelection(state.snapshot.fragments.map((f) => f.id)),
    onUndo: () => void client?.undoLastOwnOp(),
  });

  useEffect(() => {
    presence.reportSelection(view.selectedIds);
  }, [presence, view.selectedIds]);

  useEffect(() => {
    presence.reportViewport(viewport);
  }, [presence, viewport]);

  const lastEdits: Record<string, FragmentLastEdit> = useMemo(
    () => buildLastEdits(state.log),
    [state.log],
  );

  const editingFragment =
    state.snapshot.fragments.find((f) => f.id === editingId) ?? null;

  if (
    state.status === "loading" &&
    state.log.length === 0 &&
    state.snapshot.fragments.length === 0
  ) {
    return (
      <div className="flex h-full flex-col gap-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-full w-full" />
      </div>
    );
  }

  if (state.status === "error" && state.headSeq === 0) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <SquaresFourIcon />
          </EmptyMedia>
          <EmptyTitle>{BOARD_LOAD_ERROR_TITLE}</EmptyTitle>
          <EmptyDescription>{BOARD_LOAD_ERROR_DESCRIPTION}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const fitBoard = (): void => {
    const rect = readPaneRect(paneRef.current);
    if (rect) setViewport(fitToContent(state.snapshot.fragments, rect));
  };
  const zoomStep = (factor: number): void => {
    const rect = readPaneRect(paneRef.current);
    setViewport(
      rect
        ? zoomAroundCenter(viewport, factor, rect)
        : { ...viewport, zoom: clampZoom(viewport.zoom * factor) },
    );
  };
  const resetZoom = (): void => {
    const rect = readPaneRect(paneRef.current);
    setViewport(
      rect
        ? zoomTo(viewport, 1, rect)
        : { ...viewport, zoom: BOARD_FIT_MAX_ZOOM },
    );
  };

  const panelOpen =
    view.paletteOpen || view.chatOpen || view.historyOpen || view.inspectorOpen;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2.5 border-(--gray-4) border-b px-3">
        <Button
          variant="default"
          size="icon-sm"
          aria-label={BACK_TO_CANVASES_ACTION}
          onClick={() =>
            channelId
              ? navigateToSpaceCanvases(channelId)
              : navigateToCanvases()
          }
        >
          <ArrowLeftIcon />
        </Button>
        <h1 className="flex min-w-0 flex-1">
          {renaming ? (
            <HeaderTitleEditor
              initialTitle={state.name}
              onSubmit={(next) => {
                setRenaming(false);
                client?.setName(next);
                void renameBoard(boardId, next).catch((error: unknown) => {
                  client?.setName(state.name);
                  toast.error(
                    error instanceof Error ? error.message : String(error),
                  );
                });
              }}
              onCancel={() => setRenaming(false)}
              className="h-7 min-w-0 flex-1 px-1.5 font-semibold text-[15px] tracking-tight"
            />
          ) : (
            <button
              type="button"
              title={RENAME_BOARD_ACTION}
              disabled={isRenaming}
              className="min-w-0 truncate rounded-(--radius-2) px-1.5 py-0.5 text-left font-semibold text-[15px] tracking-tight transition-colors hover:bg-(--gray-3)"
              onClick={() => setRenaming(true)}
            >
              {state.name || DEFAULT_BOARD_NAME}
            </button>
          )}
        </h1>
        <div className="ml-auto flex shrink-0 items-center gap-2.5">
          <Button
            variant="default"
            size="icon-sm"
            aria-label={COPY_BOARD_LINK_ACTION}
            title={COPY_BOARD_LINK_ACTION}
            disabled={!shareChannelId}
            onClick={() => {
              if (shareChannelId) {
                void copyCanvasLink(shareChannelId, boardId, "canvas", 2);
              }
            }}
          >
            <LinkIcon />
          </Button>
          <PresenceFaces peers={peers} />
          <SyncChip status={state.status} />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="relative flex min-w-0 flex-1 flex-col">
          {view.focusedId ? null : (
            <BoardToolbar
              zoom={viewport.zoom}
              paletteOpen={view.paletteOpen}
              chatOpen={view.chatOpen}
              historyOpen={view.historyOpen}
              inspectorOpen={view.inspectorOpen}
              onZoomIn={() => zoomStep(1.2)}
              onZoomOut={() => zoomStep(1 / 1.2)}
              onZoomReset={resetZoom}
              onFitToContent={fitBoard}
              onTogglePalette={() => togglePanel("palette", view.paletteOpen)}
              onToggleChat={() => togglePanel("chat", view.chatOpen)}
              onToggleHistory={() => togglePanel("history", view.historyOpen)}
              onToggleInspector={() =>
                togglePanel("inspector", view.inspectorOpen)
              }
            />
          )}
          <div className="relative min-h-0 flex-1">
            <BoardStage
              boardId={boardId}
              paneRef={paneRef}
              snapshot={state.snapshot}
              viewport={viewport}
              setViewport={setViewport}
              applyLocal={applyLocal}
              theme={theme}
              queryClient={queryClient}
              fragmentErrors={state.fragmentErrors}
              onFragmentError={(id, message) =>
                client?.setFragmentError(id, message)
              }
              lastEdits={lastEdits}
              onEditFragment={setEditingId}
              dragActive={dragActive}
              onDropFragment={(name, world) => addFromLibrary(name, world)}
              peers={peers}
              onCursor={presence.reportCursor}
              onCaret={presence.reportCaret}
            />
            <BoardMinimap
              fragments={view.focusedId ? [] : state.snapshot.fragments}
              viewport={viewport}
              paneRect={readPaneRect(paneRef.current) ?? EMPTY_PANE}
              selectedIds={view.selectedIds}
              onJump={(world) => {
                const rect = readPaneRect(paneRef.current);
                if (!rect) return;
                setViewport({
                  zoom: viewport.zoom,
                  x: rect.width / 2 - world.x * viewport.zoom,
                  y: rect.height / 2 - world.y * viewport.zoom,
                });
              }}
            />
            {state.snapshot.fragments.length === 0 && !view.focusedId ? (
              <BoardEmptyHero
                boardId={boardId}
                boardName={state.name}
                snapshot={state.snapshot}
                headSeq={state.headSeq}
                onStarted={() => openOnly("chat")}
                onAddFragment={(name) => addFromLibrary(name)}
                onOpenLibrary={() => openOnly("palette")}
              />
            ) : null}
          </div>
        </div>

        {panelOpen ? (
          <div className="flex w-96 shrink-0 flex-col overflow-hidden">
            {view.paletteOpen ? (
              <LibraryPalette
                onAdd={(entry) => addFromLibrary(entry.name)}
                onDragStateChange={setDragActive}
                onClose={() => openOnly(null)}
              />
            ) : null}
            {view.historyOpen ? (
              <HistoryPanel
                state={state}
                onRestore={(seq) => client?.restoreTo(seq)}
                onHighlight={view.setHighlightedIds}
                onLoadFullLog={() => void client?.loadFullLog()}
                currentUserId={actorUser?.userId}
                onClose={() => openOnly(null)}
              />
            ) : null}
            {view.inspectorOpen ? (
              <StateInspector
                state={state.snapshot.state}
                fragments={state.snapshot.fragments}
                onClose={() => openOnly(null)}
              />
            ) : null}
            {view.chatOpen ? (
              <BoardChatPanel
                boardId={boardId}
                boardName={state.name}
                snapshot={state.snapshot}
                headSeq={state.headSeq}
                taskId={taskId}
                onClose={() => openOnly(null)}
              />
            ) : null}
          </div>
        ) : null}
      </div>

      <EditFragmentDialog
        open={editingId !== null}
        fragment={editingFragment}
        isPending={false}
        onOpenChange={(open) => setEditingId(open ? editingId : null)}
        applyLocal={applyLocal}
      />
    </div>
  );
}
