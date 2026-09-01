import { PlusIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { Link } from "@tanstack/react-router";

/** The templates a new doc can start from, in the order the menu shows them. */
const TEMPLATES: Array<{
  template: DocSchemas.DocTemplate;
  label: string;
  hint: string;
}> = [
  { template: "blank", label: "Empty page", hint: "start to write" },
  { template: "notes", label: "Notes", hint: "from a call" },
];

/** The docs in a space, as a tab row. The open one is marked. */
export function DocTabs({
  channelId,
  docs,
  activeDocId,
  onCreate,
  creating,
}: {
  channelId: string;
  docs: DocSchemas.DocSummary[];
  activeDocId: string | null;
  onCreate: (template: DocSchemas.DocTemplate) => void;
  creating: boolean;
}) {
  return (
    <nav className="flex min-w-0 items-center gap-1 overflow-x-auto">
      {docs.map((doc) => {
        const active = doc.id === activeDocId;
        return (
          <Button
            key={doc.id}
            size="sm"
            variant="default"
            data-selected={active || undefined}
            className={cn("shrink-0", active && "bg-fill-selected")}
            render={
              <Link
                to="/spaces/$channelId/docs/$docId"
                params={{ channelId, docId: doc.id }}
              />
            }
          >
            <span className="max-w-40 truncate">{doc.title || "Untitled"}</span>
          </Button>
        );
      })}

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              size="sm"
              variant="default"
              className="shrink-0"
              disabled={creating}
              aria-label="Make a new page"
            />
          }
        >
          <PlusIcon size={14} />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {TEMPLATES.map((entry) => (
            <DropdownMenuItem
              key={entry.template}
              onClick={() => onCreate(entry.template)}
            >
              <span className="flex flex-col">
                <span>{entry.label}</span>
                <span className="text-(--gray-11) text-xs">{entry.hint}</span>
              </span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </nav>
  );
}
