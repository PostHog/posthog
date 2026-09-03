import { XIcon } from "@phosphor-icons/react";
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
  Heading,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
  Spinner,
  Text,
} from "@posthog/quill";
import { type CanvasV2Actor, emptyCanvasV2Snapshot } from "@posthog/shared";
import {
  DIALOG_CANCEL,
  HISTORY_ACTOR_AGENT,
  HISTORY_ACTOR_UNKNOWN,
  HISTORY_ACTOR_YOU,
  HISTORY_EMPTY,
  HISTORY_LOADING,
  HISTORY_PANEL_CLOSE,
  HISTORY_RESTORE_ACTION,
  HISTORY_RESTORE_CONFIRM,
  HISTORY_RESTORE_DESCRIPTION,
  HISTORY_RESTORE_TITLE,
  TOOLBAR_HISTORY,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
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
    <div className="@container flex h-full min-h-0 w-full flex-col overflow-hidden border-border border-l">
      <div className="flex items-center justify-between gap-2 border-border border-b px-3 py-2">
        <Heading size="sm">{TOOLBAR_HISTORY}</Heading>
        {onClose ? (
          <Button
            variant="outline"
            size="icon-xs"
            aria-label={HISTORY_PANEL_CLOSE}
            onClick={onClose}
          >
            <XIcon size={12} />
          </Button>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3 py-2">
        {state.logComplete ? null : (
          <div className="flex items-center gap-2 pb-2">
            <Spinner className="size-3" />
            <Text size="xs" variant="muted">
              {HISTORY_LOADING}
            </Text>
          </div>
        )}

        {showEmpty ? (
          <Text size="sm" variant="muted">
            {HISTORY_EMPTY}
          </Text>
        ) : null}

        <ItemGroup>
          {groups.map((group) => (
            <HistoryRow
              key={group.key}
              group={group}
              isSelected={group.key === selectedKey}
              isOwn={isOwnGroup(group.actor, currentUserId)}
              onSelect={() => select(group)}
              onRestore={() => setGroupToRestore(group)}
            />
          ))}
        </ItemGroup>
      </div>

      <AlertDialog
        open={groupToRestore !== null}
        onOpenChange={(open) => {
          if (!open && !restorePending) setGroupToRestore(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{HISTORY_RESTORE_TITLE}</AlertDialogTitle>
            <AlertDialogDescription>
              {HISTORY_RESTORE_DESCRIPTION}
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
              {HISTORY_RESTORE_CONFIRM}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function HistoryRow({
  group,
  isSelected,
  isOwn,
  onSelect,
  onRestore,
}: {
  group: HistoryGroup;
  isSelected: boolean;
  isOwn: boolean;
  onSelect: () => void;
  onRestore: () => void;
}): ReactElement {
  return (
    <Item
      variant="pressable"
      size="sm"
      className={isSelected ? "ring-1 ring-border" : undefined}
      onClick={onSelect}
    >
      <ItemContent className="min-w-0">
        <ItemTitle className="flex min-w-0 flex-wrap items-center gap-x-2">
          <span className="truncate">{actorName(group.actor)}</span>
          {isOwn ? (
            <Text size="xxs" variant="muted">
              {HISTORY_ACTOR_YOU}
            </Text>
          ) : null}
          <Text size="xs" variant="muted">
            {formatMinute(group.minuteIso)}
          </Text>
        </ItemTitle>
        <ItemDescription className="break-words">
          {group.descriptions.join(", ")}
        </ItemDescription>
      </ItemContent>
      <ItemActions className="shrink-0">
        <Button
          variant="outline"
          size="xs"
          onClick={(event) => {
            event.stopPropagation();
            onRestore();
          }}
        >
          {HISTORY_RESTORE_ACTION}
        </Button>
      </ItemActions>
    </Item>
  );
}

function actorName(actor: CanvasV2Actor): string {
  if (actor.userName) return actor.userName;
  if (actor.kind === "agent") return HISTORY_ACTOR_AGENT;
  return HISTORY_ACTOR_UNKNOWN;
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
