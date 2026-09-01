import { ChatCircleTextIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Input,
  Text,
} from "@posthog/quill";
import { useEffect, useState } from "react";
import type { DocConnectionStatus } from "../collab/useDocCollab";

const STATUS_LABELS: Record<DocSchemas.DocStatus, string> = {
  draft: "Draft",
  active: "Active",
  done: "Done",
};

const CONNECTION_LABELS: Record<DocConnectionStatus, string> = {
  connecting: "Connecting",
  live: "Live",
  offline: "Offline",
};

/** The doc's title, where it is in its life, and whether the page is live. */
export function DocHeader({
  doc,
  version,
  connection,
  discussionCount,
  onRename,
  onStatusChange,
  onOpenDiscussions,
}: {
  doc: DocSchemas.Doc;
  version: number;
  connection: DocConnectionStatus;
  discussionCount: number;
  onRename: (title: string) => void;
  onStatusChange: (status: DocSchemas.DocStatus) => void;
  onOpenDiscussions: () => void;
}) {
  const [title, setTitle] = useState(doc.title);
  useEffect(() => setTitle(doc.title), [doc.title]);

  return (
    <header className="flex min-w-0 flex-wrap items-center gap-2 border-(--gray-5) border-b px-4 py-2">
      <Input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        onBlur={() => title !== doc.title && onRename(title)}
        aria-label="Doc title"
        className="min-w-40 flex-1 border-none bg-transparent font-medium text-base shadow-none"
        placeholder="Untitled"
      />

      <Text size="sm" className="shrink-0 text-(--gray-11)">
        v{version} · {CONNECTION_LABELS[connection]}
      </Text>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Badge variant="default" className="shrink-0 cursor-pointer" />
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

      <Button
        size="sm"
        variant="default"
        className="shrink-0"
        onClick={onOpenDiscussions}
      >
        <ChatCircleTextIcon size={14} />
        Discussions
        {discussionCount > 0 ? (
          <Badge variant="info">{discussionCount}</Badge>
        ) : null}
      </Button>
    </header>
  );
}
