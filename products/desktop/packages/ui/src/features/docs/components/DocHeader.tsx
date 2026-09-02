import {
  CaretDownIcon,
  ChatCircleTextIcon,
  CheckIcon,
  CloudSlashIcon,
  DotsThreeIcon,
} from "@phosphor-icons/react";
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

/** The status is a dot before a word: colour carries the state and the row stays quiet. */
const STATUS_DOTS: Record<DocSchemas.DocStatus, string> = {
  draft: "bg-(--gray-8)",
  active: "bg-(--primary)",
  done: "bg-(--grass-9)",
};

const CONNECTION_LABELS: Record<DocConnectionStatus, string> = {
  connecting: "Saving…",
  live: "Saved",
  offline: "Offline",
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
  threadCount,
  onStatusChange,
  onOpenThreads,
  onJumpToPeer,
  onDelete,
}: {
  spaceName: string;
  doc: DocSchemas.Doc;
  version: number;
  connection: DocConnectionStatus;
  peers: RemoteCaret[];
  threadCount: number;
  onStatusChange: (status: DocSchemas.DocStatus) => void;
  onOpenThreads: () => void;
  onJumpToPeer: (clientId: string) => void;
  /** Absent for the space's own notes, which cannot be deleted. */
  onDelete?: () => void;
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
            <span
              className={cn(
                "mr-1 flex shrink-0 items-center gap-1 text-[11.5px]",
                connection === "offline"
                  ? "text-(--amber-11)"
                  : "text-(--gray-9)",
              )}
            />
          }
        >
          {connection === "offline" ? (
            <CloudSlashIcon size={12} />
          ) : connection === "live" ? (
            <CheckIcon size={12} />
          ) : null}
          {CONNECTION_LABELS[connection]}
        </TooltipTrigger>
        <TooltipContent>Version {version}</TooltipContent>
      </Tooltip>

      {peers.length > 0 ? (
        <DocFaces peers={peers} onJump={onJumpToPeer} />
      ) : null}

      <DropdownMenu>
        <DropdownMenuTrigger
          render={<Button size="sm" variant="default" className="shrink-0" />}
        >
          <span
            className={cn("size-1.5 rounded-full", STATUS_DOTS[doc.status])}
          />
          {STATUS_LABELS[doc.status]}
          <CaretDownIcon size={10} className="text-(--gray-9)" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {(Object.keys(STATUS_LABELS) as DocSchemas.DocStatus[]).map(
            (status) => (
              <DropdownMenuItem
                key={status}
                onClick={() => onStatusChange(status)}
              >
                <span
                  className={cn("size-1.5 rounded-full", STATUS_DOTS[status])}
                />
                {STATUS_LABELS[status]}
              </DropdownMenuItem>
            ),
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <Button
        size="sm"
        variant="default"
        className="shrink-0"
        onClick={onOpenThreads}
      >
        <ChatCircleTextIcon size={13} />
        Threads
        {threadCount > 0 ? (
          <span className="text-(--gray-9)">{threadCount}</span>
        ) : null}
      </Button>

      {onDelete ? (
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                size="icon"
                variant="default"
                aria-label="Page actions"
                className="shrink-0"
              />
            }
          >
            <DotsThreeIcon size={15} />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onDelete}>Delete page…</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </header>
  );
}
