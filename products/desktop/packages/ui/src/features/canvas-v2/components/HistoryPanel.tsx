import {
  type BoardSyncState,
  groupLogEntries,
  type HistoryGroup,
} from "@posthog/core/canvas-v2/boardSync";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Spinner,
  Text,
} from "@posthog/quill";
import { type CanvasV2Actor, emptyCanvasV2Snapshot } from "@posthog/shared";
import {
  DIALOG_CANCEL,
  TOOLBAR_HISTORY,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { BoardPanel } from "@posthog/ui/features/canvas-v2/components/BoardPanel";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";

export interface HistoryPanelProps {
  state: BoardSyncState;
  /**
   * `BoardSyncClient.restoreTo` returns a promise, so the panel awaits this and
   * owns the pending state of the restore button itself.
   */
  onRestore: (seq: number) => void | Promise<void>;
  onHighlight: (fragmentIds: string[]) => void;
  onLoadFullLog: () => void;
  currentUserId?: number;
  onClose?: () => void;
}

const CLOCK = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** The op log as rows, newest first, with a restore action per group. */
export function HistoryPanel({
  state,
  onRestore,
  onHighlight,
  onLoadFullLog,
  currentUserId,
  onClose,
}: HistoryPanelProps): ReactElement {
  const requestedFullLog = useRef(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [groupToRestore, setGroupToRestore] = useState<HistoryGroup | null>(
    null,
  );
  const [restorePending, setRestorePending] = useState(false);

  useEffect(() => {
    if (requestedFullLog.current || state.logComplete) return;
    requestedFullLog.current = true;
    onLoadFullLog();
  }, [state.logComplete, onLoadFullLog]);

  const groups = useMemo(
    () => groupLogEntries(state.log, emptyCanvasV2Snapshot()),
    [state.log],
  );

  const select = (group: HistoryGroup): void => {
    setSelectedKey(group.key);
    onHighlight(group.fragmentIds);
  };

  const confirmRestore = async (): Promise<void> => {
    if (!groupToRestore || restorePending) return;
    setRestorePending(true);
    try {
      await onRestore(groupToRestore.lastSeq);
      setGroupToRestore(null);
    } finally {
      setRestorePending(false);
    }
  };

  const showEmpty = groups.length === 0 && state.logComplete;

  return (
    <BoardPanel
      title={TOOLBAR_HISTORY}
      closeLabel="Close history"
      onClose={onClose}
    >
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3 py-2">
        {state.logComplete ? null : (
          <div className="flex items-center gap-2 pb-2">
            <Spinner className="size-3" />
            <Text size="xs" variant="muted">
              Loading the rest of the history…
            </Text>
          </div>
        )}

        {showEmpty ? (
          <Text size="sm" variant="muted">
            No changes yet.
          </Text>
        ) : null}

        <div className="flex flex-col">
          {groups.map((group) => (
            <HistoryRow
              key={group.key}
              group={group}
              isSelected={group.key === selectedKey}
              isOwn={isOwnGroup(group.actor, currentUserId)}
              isLast={group.key === groups[groups.length - 1]?.key}
              onSelect={() => select(group)}
              onRestore={() => setGroupToRestore(group)}
            />
          ))}
        </div>
      </div>

      <AlertDialog
        open={groupToRestore !== null}
        onOpenChange={(open) => {
          if (!open && !restorePending) setGroupToRestore(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Restore the board to this point?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This adds a new change. Nothing in the history is lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              variant="outline"
              disabled={restorePending}
              onClick={() => setGroupToRestore(null)}
            >
              {DIALOG_CANCEL}
            </Button>
            <Button
              variant="primary"
              loading={restorePending}
              disabled={restorePending}
              onClick={() => void confirmRestore()}
            >
              Restore board
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </BoardPanel>
  );
}

function HistoryRow({
  group,
  isSelected,
  isOwn,
  isLast,
  onSelect,
  onRestore,
}: {
  group: HistoryGroup;
  isSelected: boolean;
  isOwn: boolean;
  isLast: boolean;
  onSelect: () => void;
  onRestore: () => void;
}): ReactElement {
  return (
    <div
      className={`group/row relative flex gap-2.5 rounded-(--radius-2) py-1.5 pr-1.5 pl-1 transition-colors hover:bg-(--gray-3) ${
        isSelected ? "bg-(--gray-3)" : ""
      }`}
    >
      <button
        type="button"
        className="absolute inset-0 rounded-(--radius-2)"
        onClick={onSelect}
      >
        <span className="sr-only">{group.descriptions[0] ?? ""}</span>
      </button>
      <span className="relative flex w-3 shrink-0 justify-center pt-1.5">
        {isLast ? null : (
          <span className="absolute top-4 bottom-[-10px] w-px bg-(--gray-a5)" />
        )}
        <span
          className={`z-10 size-2 rounded-full ${
            isOwn ? "bg-(--accent-9)" : "bg-(--gray-8)"
          }`}
        />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5 py-0.5">
        <span className="flex min-w-0 items-baseline gap-1.5">
          <span className="truncate font-medium text-[12px]">
            {actorName(group.actor)}
          </span>
          {isOwn ? (
            <span className="shrink-0 text-(--gray-10) text-[11px]">you</span>
          ) : null}
          <span className="ml-auto shrink-0 text-(--gray-10) text-[11px] tabular-nums">
            {formatMinute(group.minuteIso)}
          </span>
        </span>
        <span className="line-clamp-2 text-(--gray-11) text-[12px] leading-snug">
          {summarize(group.descriptions)}
        </span>
      </span>
      <span className="-translate-y-1/2 absolute top-1/2 right-1.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover/row:opacity-100">
        <Button
          variant="outline"
          size="xs"
          onClick={(event) => {
            event.stopPropagation();
            onRestore();
          }}
        >
          Restore
        </Button>
      </span>
    </div>
  );
}

function summarize(descriptions: readonly string[]): string {
  const first = descriptions[0];
  if (!first) return "";
  const lead = first.charAt(0).toUpperCase() + first.slice(1);
  if (descriptions.length === 1) return lead;
  return `${lead}, and ${descriptions.length - 1} more`;
}

function actorName(actor: CanvasV2Actor): string {
  if (actor.userName) return actor.userName;
  if (actor.kind === "agent") return "Agent";
  return "Someone";
}

function isOwnGroup(actor: CanvasV2Actor, currentUserId?: number): boolean {
  if (currentUserId === undefined) return false;
  return actor.kind === "user" && actor.userId === currentUserId;
}

function formatMinute(minuteIso: string): string {
  const at = Date.parse(minuteIso);
  if (Number.isNaN(at)) return minuteIso;
  return CLOCK.format(at);
}
