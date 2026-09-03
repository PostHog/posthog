import { SquaresFourIcon } from "@phosphor-icons/react";
import {
  BOARD_FIT_MAX_ZOOM,
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
  Text,
} from "@posthog/quill";
import type { CanvasV2Fragment, CanvasV2Op } from "@posthog/shared";
import {
  CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT,
  CANVAS_V2_FRAGMENT_DEFAULT_WIDTH,
  findFreeSpot,
  maxZ,
} from "@posthog/shared";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  BACK_TO_BOARDS_ACTION,
  BOARD_EMPTY_HINT,
  BOARD_LOAD_ERROR_DESCRIPTION,
  BOARD_LOAD_ERROR_TITLE,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { useApplyBoardToolCalls } from "@posthog/ui/features/canvas-v2/hooks/useApplyBoardToolCalls";
import { useBoardApi } from "@posthog/ui/features/canvas-v2/hooks/useBoardApi";
import { useBoardKeyboard } from "@posthog/ui/features/canvas-v2/hooks/useBoardKeyboard";
import {
  useBoardTaskId,
  useBoardViewport,
  useBoardViewportStore,
} from "@posthog/ui/features/canvas-v2/hooks/useBoardViewportStore";
import { useBoardViewStore } from "@posthog/ui/features/canvas-v2/interaction/boardViewStore";
import { libraryEntry } from "@posthog/ui/features/canvas-v2/library/registry";
import { useBoardSync } from "@posthog/ui/features/canvas-v2/sync/useBoardSync";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { navigateToCanvasesV2 } from "@posthog/ui/router/navigationBridge";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useQueryClient } from "@tanstack/react-query";
import {
  type ReactElement,
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";
import { readPaneRect } from "../interaction/useBoardPointer";
import { buildLastEdits } from "../lastEdits";
import { BoardChatPanel } from "./BoardChatPanel";
import { BoardStage } from "./BoardStage";
import { BoardToolbar } from "./BoardToolbar";
import { EditFragmentDialog } from "./EditFragmentDialog";
import type { FragmentLastEdit } from "./FragmentOverlay";
import { HistoryPanel } from "./HistoryPanel";
import { LibraryPalette } from "./LibraryPalette";
import { StateInspector } from "./StateInspector";
import { SyncChip } from "./SyncChip";

/** One board: the stage, its chrome, and the side panels. */
export function BoardView({ boardId }: { boardId: string }): ReactElement {
  const paneRef = useRef<HTMLDivElement | null>(null);
  const queryClient = useQueryClient();
  const api = useBoardApi();
  const currentUser = useCurrentUser();
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

  const viewport = useBoardViewport(boardId);
  const setViewportForBoard = useBoardViewportStore((s) => s.setViewport);
  const setViewport = useCallback(
    (next: typeof viewport) => setViewportForBoard(boardId, next),
    [boardId, setViewportForBoard],
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
  const [editingId, setEditingId] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const applyLocal = useCallback(
    (ops: CanvasV2Op[]) => client?.applyLocal(ops),
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
        id: nextFragmentId(entry.name, snapshot.fragments),
        title: entry.label,
        x: Math.round(spot.x),
        y: Math.round(spot.y),
        w: size.w,
        h: size.h,
        z: maxZ(snapshot) + 1,
        code: entry.code,
        codeVersion: 1,
      };
      client.applyLocal([{ type: "add_fragment", fragment }]);
      view.setSelectedId(fragment.id);
    },
    [client, view],
  );

  useApplyBoardToolCalls(client, taskId, view.setSelectedId);

  useBoardKeyboard({
    enabled: editingId === null,
    paneRef,
    fragments: state.snapshot.fragments,
    viewport,
    setViewport,
    selectedId: view.selectedId,
    onDeleteSelected: (id) => applyLocal([{ type: "remove_fragment", id }]),
    onClearSelection: () => view.setSelectedId(null),
    onUndo: () => void client?.undoLastOwnOp(),
  });

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
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>{state.name || " "}</PageHeaderTitle>
            <PageHeaderActions>
              <Button variant="outline" onClick={() => navigateToCanvasesV2()}>
                {BACK_TO_BOARDS_ACTION}
              </Button>
            </PageHeaderActions>
          </PageHeaderTitleRow>
        </PageHeaderHeading>
      </PageHeader>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
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
            syncChip={
              <SyncChip
                status={state.status}
                log={state.log}
                currentUserId={actorUser?.userId}
              />
            }
          />
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
            />
            {state.snapshot.fragments.length === 0 ? (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <Text size="sm" variant="muted">
                  {BOARD_EMPTY_HINT}
                </Text>
              </div>
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

function nextFragmentId(
  base: string,
  fragments: readonly CanvasV2Fragment[],
): string {
  const taken = new Set(fragments.map((f) => f.id));
  if (!taken.has(base)) return base;
  for (let index = 2; index < 1000; index++) {
    const candidate = `${base}-${index}`;
    if (!taken.has(candidate)) return candidate;
  }
  return `${base}-${Date.now()}`;
}
