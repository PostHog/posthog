import { ChatCircleTextIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { RemoteCaret } from "../collab/remoteCarets";
import type { DocConnectionStatus } from "../collab/useDocCollab";
import { DocFaces } from "./DocFaces";

const STATUS_LABELS: Record<DocSchemas.DocStatus, string> = {
  draft: "Draft",
  active: "Active",
  done: "Done",
};

/** The status is a word, not a pill: colour carries the state and the row stays quiet. */
const STATUS_TONES: Record<DocSchemas.DocStatus, string> = {
  draft: "text-(--gray-11)",
  active: "text-(--primary)",
  done: "text-(--grass-11)",
};

const CONNECTION_LABELS: Record<DocConnectionStatus, string> = {
  connecting: "saving",
  live: "saved",
  offline: "offline",
};

/**
 * The row above the doc: where you are on the left, what the doc is on the right.
 *
 * The title is not here. It belongs to the document, at the top of the page, the
 * way it reads when someone opens the doc.
 */
export function DocHeader({
  spaceName,
  doc,
  version,
  connection,
  peers,
  discussionCount,
  onStatusChange,
  onOpenDiscussions,
  onJumpToPeer,
}: {
  spaceName: string;
  doc: DocSchemas.Doc;
  version: number;
  connection: DocConnectionStatus;
  peers: RemoteCaret[];
  discussionCount: number;
  onStatusChange: (status: DocSchemas.DocStatus) => void;
  onOpenDiscussions: () => void;
  onJumpToPeer: (clientId: string) => void;
}) {
  return (
    <header className="flex min-w-0 items-center gap-2 border-(--gray-5) border-b px-4 py-1.5">
      <div className="flex min-w-0 items-center gap-1.5 text-xs">
        <span className="shrink-0 text-(--gray-11)">{spaceName}</span>
        <span className="shrink-0 text-(--gray-8)">/</span>
        <span className="truncate text-(--gray-12)">
          {doc.title || "Untitled"}
        </span>
      </div>

      <div className="flex-1" />

      <Tooltip>
        <TooltipTrigger
          render={
            <span className="shrink-0 text-(--gray-9) text-xs">
              {CONNECTION_LABELS[connection]}
            </span>
          }
        />
        <TooltipContent>Version {version}</TooltipContent>
      </Tooltip>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <button
              type="button"
              className={cn(
                "shrink-0 cursor-pointer px-1 font-medium text-xs",
                STATUS_TONES[doc.status],
              )}
            />
          }
        >
          {STATUS_LABELS[doc.status]}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {(Object.keys(STATUS_LABELS) as DocSchemas.DocStatus[]).map(
            (status) => (
              <DropdownMenuItem
                key={status}
                onClick={() => onStatusChange(status)}
              >
                {STATUS_LABELS[status]}
              </DropdownMenuItem>
            ),
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {peers.length > 0 ? (
        <DocFaces peers={peers} onJump={onJumpToPeer} />
      ) : null}

      <Button
        size="sm"
        variant="default"
        className="shrink-0"
        onClick={onOpenDiscussions}
      >
        <ChatCircleTextIcon size={13} />
        Discussions
        {discussionCount > 0 ? (
          <span className="text-(--gray-9)">{discussionCount}</span>
        ) : null}
      </Button>
    </header>
  );
}
