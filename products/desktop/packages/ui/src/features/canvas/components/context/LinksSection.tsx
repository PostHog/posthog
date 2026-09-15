import {
  ArrowSquareOutIcon,
  FileTextIcon,
  LinkIcon,
  PaperclipIcon,
  PlusIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import {
  type ContextLink,
  isHttpUrl,
} from "@posthog/core/canvas/contextDocument";
import {
  Button,
  Input,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useState } from "react";
import { SectionCard, SectionPlaceholder } from "./SectionCard";

interface LinksSectionProps {
  links: ContextLink[];
  onChange: (links: ContextLink[]) => Promise<void>;
  isSaving: boolean;
}

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function titleFromTarget(target: string): string {
  if (isHttpUrl(target)) {
    try {
      const url = new URL(target);
      const last = url.pathname.split("/").filter(Boolean).pop();
      return last ? decodeURIComponent(last).replace(/[-_]+/g, " ") : url.host;
    } catch {
      return target;
    }
  }
  return target;
}

/** Documents, specs, dashboards elsewhere, and repository files agents should open. */
export function LinksSection({ links, onChange, isSaving }: LinksSectionProps) {
  const [adding, setAdding] = useState(false);
  const showForm = adding || links.length === 0;

  const remove = (index: number) =>
    onChange(links.filter((_, i) => i !== index));

  const add = async (link: ContextLink) => {
    await onChange([...links, link]);
    setAdding(false);
  };

  return (
    <SectionCard
      icon={<PaperclipIcon size={16} />}
      title="Files and links"
      description="Specs, docs, and repository files that hold more detail than fits here."
      count={links.length}
      actions={
        !showForm ? (
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            <PlusIcon size={14} />
            Add
          </Button>
        ) : null
      }
    >
      {links.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border">
          {links.map((link, index) => {
            const external = isHttpUrl(link.target);
            return (
              <li key={`${link.target}-${index}`} className="group/link">
                <Item
                  variant="default"
                  size="sm"
                  className="rounded-none border-0 px-4"
                >
                  <ItemMedia variant="icon">
                    {external ? (
                      <LinkIcon size={16} />
                    ) : (
                      <FileTextIcon size={16} />
                    )}
                  </ItemMedia>
                  <ItemContent className="min-w-0">
                    <ItemTitle className="truncate">
                      {external ? (
                        <button
                          type="button"
                          className="truncate text-left hover:underline"
                          onClick={() => openExternalUrl(link.target)}
                        >
                          {link.title}
                        </button>
                      ) : (
                        link.title
                      )}
                    </ItemTitle>
                    <ItemDescription className="truncate">
                      {link.note ? `${link.note} · ` : ""}
                      <span className={external ? "" : "font-mono"}>
                        {external ? hostOf(link.target) : link.target}
                      </span>
                    </ItemDescription>
                  </ItemContent>
                  <ItemActions className="opacity-0 transition-opacity group-focus-within/link:opacity-100 group-hover/link:opacity-100">
                    {external ? (
                      <Tooltip>
                        <TooltipTrigger
                          render={
                            <Button
                              variant="default"
                              size="icon-xs"
                              aria-label={`Open ${link.title}`}
                              onClick={() => openExternalUrl(link.target)}
                            />
                          }
                        >
                          <ArrowSquareOutIcon size={14} />
                        </TooltipTrigger>
                        <TooltipContent>Open</TooltipContent>
                      </Tooltip>
                    ) : null}
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            variant="default"
                            size="icon-xs"
                            aria-label={`Remove ${link.title}`}
                            disabled={isSaving}
                            onClick={() => void remove(index)}
                          />
                        }
                      >
                        <TrashIcon size={14} />
                      </TooltipTrigger>
                      <TooltipContent>Remove</TooltipContent>
                    </Tooltip>
                  </ItemActions>
                </Item>
              </li>
            );
          })}
        </ul>
      ) : null}

      {showForm ? (
        <AddLinkForm
          onAdd={add}
          onCancel={links.length > 0 ? () => setAdding(false) : undefined}
          isSaving={isSaving}
        />
      ) : null}
    </SectionCard>
  );
}

function AddLinkForm({
  onAdd,
  onCancel,
  isSaving,
}: {
  onAdd: (link: ContextLink) => Promise<void>;
  onCancel?: () => void;
  isSaving: boolean;
}) {
  const [target, setTarget] = useState("");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const trimmed = target.trim();
  const canAdd = trimmed.length > 0 && !isSaving;

  const submit = async () => {
    if (!canAdd) return;
    await onAdd({
      target: trimmed,
      title: title.trim() || titleFromTarget(trimmed),
      note: note.trim(),
    });
    setTarget("");
    setTitle("");
    setNote("");
  };

  return (
    <form
      className="flex flex-col gap-2 border-border border-t px-4 py-3 first:border-t-0"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      {onCancel === undefined ? (
        <SectionPlaceholder className="px-0 pt-2 pb-3">
          <Text size="xs" weight="medium">
            No files or links yet
          </Text>
          <Text size="xs" variant="muted">
            Paste a URL, or a repository path like{" "}
            <code className="font-mono">docs/architecture.md</code>.
          </Text>
        </SectionPlaceholder>
      ) : null}
      <div className="grid @lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2">
        <Input
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="https://… or path/to/file.md"
          aria-label="URL or repository path"
          autoFocus={onCancel !== undefined}
          className="font-mono text-xs"
        />
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title (optional)"
          aria-label="Title"
        />
        <Input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Why it matters (optional)"
          aria-label="Note"
        />
      </div>
      <div className="flex items-center justify-end gap-2">
        {onCancel ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={isSaving}
          >
            Cancel
          </Button>
        ) : null}
        <Button type="submit" variant="primary" size="sm" disabled={!canAdd}>
          <PlusIcon size={14} />
          Add
        </Button>
      </div>
    </form>
  );
}
