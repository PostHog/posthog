import { ListIcon, PlusIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import {
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { Link, useNavigate } from "@tanstack/react-router";

/** The templates a new doc can start from, in the order the menu shows them. */
const TEMPLATES: Array<{
  template: DocSchemas.DocTemplate;
  label: string;
  hint: string;
}> = [
  { template: "blank", label: "Empty page", hint: "start to write" },
  { template: "notes", label: "Notes", hint: "from a call" },
];

const STATUS_TONES: Record<DocSchemas.DocStatus, string> = {
  draft: "text-(--gray-11)",
  active: "text-(--primary)",
  done: "text-(--grass-11)",
};

/**
 * The space's docs, along the bottom of the pane.
 *
 * A space is one document and its pages sit in this row, so the row stays put
 * while the page above it changes. The list button reaches every page when the
 * row runs out of width.
 */
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
  const navigate = useNavigate();

  return (
    <nav className="flex h-9 shrink-0 items-center gap-[3px] overflow-x-auto border-(--gray-5) border-t bg-(--gray-2) px-3.5">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <button
              type="button"
              aria-label="All pages"
              className="relative top-[2px] grid h-[22px] w-[26px] shrink-0 cursor-pointer place-items-center rounded-(--radius-1) text-(--gray-9) hover:bg-(--gray-4) hover:text-(--gray-12)"
            />
          }
        >
          <ListIcon size={13} />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuLabel>Pages in this space</DropdownMenuLabel>
          {docs.map((doc) => (
            <DropdownMenuItem
              key={doc.id}
              onClick={() =>
                void navigate({
                  to: "/spaces/$channelId/docs/$docId",
                  params: { channelId, docId: doc.id },
                })
              }
            >
              <span className="flex min-w-0 flex-1 items-center gap-2">
                <span className="truncate">{doc.title || "Untitled"}</span>
                <span className={cn("text-xs", STATUS_TONES[doc.status])}>
                  {doc.status}
                </span>
              </span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {docs.map((doc) => {
        const active = doc.id === activeDocId;
        return (
          <Link
            key={doc.id}
            to="/spaces/$channelId/docs/$docId"
            params={{ channelId, docId: doc.id }}
            className={cn(
              "flex h-[26px] shrink-0 items-center gap-1.5 rounded-t-(--radius-1) px-[13px] text-xs",
              active
                ? "border-(--gray-5) border-x border-t bg-(--gray-1) font-medium text-(--gray-12)"
                : "text-(--gray-11) hover:bg-(--gray-4)",
            )}
          >
            <span className="max-w-40 truncate">{doc.title || "Untitled"}</span>
          </Link>
        );
      })}

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <button
              type="button"
              aria-label="Make a new page"
              disabled={creating}
              className="relative top-[2px] grid h-[22px] w-6 shrink-0 cursor-pointer place-items-center rounded-(--radius-1) text-(--gray-9) hover:bg-(--gray-4) hover:text-(--gray-12)"
            />
          }
        >
          <PlusIcon size={13} />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuLabel>Make a new page</DropdownMenuLabel>
          <DropdownMenuSeparator />
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

      <span className="flex-1" />
      <span className="shrink-0 whitespace-nowrap pr-0.5 text-(--gray-9) text-[11px]">
        {docs.length} {docs.length === 1 ? "page" : "pages"} in this space
      </span>
    </nav>
  );
}
