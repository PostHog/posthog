import { DotsThreeIcon, SquaresFourIcon } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Card,
  CardHeader,
  CardTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Skeleton,
  Text,
} from "@posthog/quill";
import type { CanvasV2BoardSummary } from "@posthog/shared";
import {
  BOARD_CREATE_ERROR,
  BOARD_DELETE_ERROR,
  BOARD_LIST_EMPTY_DESCRIPTION,
  BOARD_LIST_EMPTY_TITLE,
  BOARD_LIST_ERROR_DESCRIPTION,
  BOARD_LIST_ERROR_TITLE,
  BOARD_RENAME_ERROR,
  CANVASES_V2_DESCRIPTION,
  CANVASES_V2_TITLE,
  DELETE_BOARD_ACTION,
  DELETE_BOARD_CONFIRM,
  DELETE_BOARD_DESCRIPTION,
  DELETE_BOARD_TITLE,
  DIALOG_CANCEL,
  fragmentCountLabel,
  NEW_BOARD_ACTION,
  RENAME_BOARD_ACTION,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import {
  type BoardNameDialogMode,
  NewBoardDialog,
} from "@posthog/ui/features/canvas-v2/components/NewBoardDialog";
import { useCanvasV2BoardMutations } from "@posthog/ui/features/canvas-v2/hooks/useCanvasV2BoardMutations";
import { useCanvasV2Boards } from "@posthog/ui/features/canvas-v2/hooks/useCanvasV2Boards";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToCanvasesV2 } from "@posthog/ui/router/navigationBridge";
import { type ReactElement, useState } from "react";

function errorDescription(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function BoardCard({
  board,
  onRename,
  onDelete,
}: {
  board: CanvasV2BoardSummary;
  onRename: () => void;
  onDelete: () => void;
}): ReactElement {
  return (
    <Card className="relative">
      <CardHeader>
        <CardTitle className="pr-8">{board.name}</CardTitle>
        <div className="flex items-center gap-2">
          <Text size="xs" variant="muted">
            {fragmentCountLabel(board.fragmentCount)}
          </Text>
          <RelativeTimestamp timestamp={board.updatedAt} />
        </div>
      </CardHeader>
      <button
        type="button"
        className="absolute inset-0 rounded-(--radius-3)"
        onClick={() => navigateToCanvasesV2(board.id)}
      >
        <span className="sr-only">{board.name}</span>
      </button>
      <div className="absolute top-2 right-2 z-10">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button variant="default" size="icon-sm" aria-label={board.name}>
                <DotsThreeIcon />
              </Button>
            }
          />
          <DropdownMenuContent>
            <DropdownMenuItem onClick={onRename}>
              {RENAME_BOARD_ACTION}
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={onDelete}>
              {DELETE_BOARD_ACTION}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </Card>
  );
}

export function CanvasesV2ListView(): ReactElement {
  const { boards, isLoading, isError } = useCanvasV2Boards();
  const {
    createBoard,
    renameBoard,
    removeBoard,
    isCreating,
    isRenaming,
    isRemoving,
  } = useCanvasV2BoardMutations();
  const [nameDialog, setNameDialog] = useState<{
    mode: BoardNameDialogMode;
    board?: CanvasV2BoardSummary;
  } | null>(null);
  const [boardToDelete, setBoardToDelete] =
    useState<CanvasV2BoardSummary | null>(null);

  const submitName = async (name: string) => {
    const dialog = nameDialog;
    if (!dialog) return;
    try {
      if (dialog.mode === "rename" && dialog.board) {
        await renameBoard(dialog.board.id, name);
        setNameDialog(null);
        return;
      }
      const board = await createBoard(name);
      setNameDialog(null);
      navigateToCanvasesV2(board.id);
    } catch (error) {
      toast.error(
        dialog.mode === "rename" ? BOARD_RENAME_ERROR : BOARD_CREATE_ERROR,
        { description: errorDescription(error) },
      );
    }
  };

  const confirmDelete = async () => {
    if (!boardToDelete) return;
    try {
      await removeBoard(boardToDelete.id);
      setBoardToDelete(null);
    } catch (error) {
      toast.error(BOARD_DELETE_ERROR, {
        description: errorDescription(error),
      });
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>{CANVASES_V2_TITLE}</PageHeaderTitle>
            <PageHeaderActions>
              <Button
                variant="primary"
                onClick={() => setNameDialog({ mode: "create" })}
              >
                {NEW_BOARD_ACTION}
              </Button>
            </PageHeaderActions>
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            {CANVASES_V2_DESCRIPTION}
          </PageHeaderDescription>
        </PageHeaderHeading>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <BoardListBody
          boards={boards}
          isLoading={isLoading}
          isError={isError}
          onCreate={() => setNameDialog({ mode: "create" })}
          onRename={(board) => setNameDialog({ mode: "rename", board })}
          onDelete={setBoardToDelete}
        />
      </div>

      <NewBoardDialog
        open={nameDialog !== null}
        mode={nameDialog?.mode ?? "create"}
        initialName={nameDialog?.board?.name ?? ""}
        isPending={isCreating || isRenaming}
        onOpenChange={(open) => {
          if (!open) setNameDialog(null);
        }}
        onSubmit={(name) => void submitName(name)}
      />

      <AlertDialog
        open={boardToDelete !== null}
        onOpenChange={(open) => {
          if (!open && !isRemoving) setBoardToDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{DELETE_BOARD_TITLE}</AlertDialogTitle>
            <AlertDialogDescription>
              {DELETE_BOARD_DESCRIPTION}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              variant="outline"
              disabled={isRemoving}
              onClick={() => setBoardToDelete(null)}
            >
              {DIALOG_CANCEL}
            </Button>
            <Button
              variant="destructive"
              loading={isRemoving}
              disabled={isRemoving}
              onClick={() => void confirmDelete()}
            >
              {DELETE_BOARD_CONFIRM}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function BoardListBody({
  boards,
  isLoading,
  isError,
  onCreate,
  onRename,
  onDelete,
}: {
  boards: CanvasV2BoardSummary[];
  isLoading: boolean;
  isError: boolean;
  onCreate: () => void;
  onRename: (board: CanvasV2BoardSummary) => void;
  onDelete: (board: CanvasV2BoardSummary) => void;
}): ReactElement {
  if (isLoading) {
    return (
      <div className="grid @min-[640px]:grid-cols-2 @min-[960px]:grid-cols-3 grid-cols-1 gap-3">
        {[0, 1, 2].map((key) => (
          <Skeleton key={key} className="h-24 w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <SquaresFourIcon />
          </EmptyMedia>
          <EmptyTitle>{BOARD_LIST_ERROR_TITLE}</EmptyTitle>
          <EmptyDescription>{BOARD_LIST_ERROR_DESCRIPTION}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (boards.length === 0) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <SquaresFourIcon />
          </EmptyMedia>
          <EmptyTitle>{BOARD_LIST_EMPTY_TITLE}</EmptyTitle>
          <EmptyDescription>{BOARD_LIST_EMPTY_DESCRIPTION}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button variant="primary" onClick={onCreate}>
            {NEW_BOARD_ACTION}
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  return (
    <div className="@container">
      <div className="grid @min-[640px]:grid-cols-2 @min-[960px]:grid-cols-3 grid-cols-1 gap-3">
        {boards.map((board) => (
          <BoardCard
            key={board.id}
            board={board}
            onRename={() => onRename(board)}
            onDelete={() => onDelete(board)}
          />
        ))}
      </div>
    </div>
  );
}
