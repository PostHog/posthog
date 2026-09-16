import { XIcon } from "@phosphor-icons/react";
import type {
  ContextLink,
  ContextObject,
} from "@posthog/core/canvas/contextDocument";
import {
  Autocomplete,
  AutocompleteCollection,
  AutocompleteGroup,
  AutocompleteInput,
  AutocompleteItem,
  AutocompleteLabel,
  AutocompleteList,
  Button,
  cn,
  Dialog,
  DialogContent,
  Input,
} from "@posthog/quill";
import { useContextSources } from "@posthog/ui/features/canvas/hooks/useContextSources";
import { CommandKeyHints } from "@posthog/ui/features/command/CommandKeyHints";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import {
  type AddContextRow,
  type AddContextScope,
  type AddContextSection,
  buildAddContextView,
  parseAddition,
  scopeHint,
  scopeLabel,
} from "./addContextRows";

interface AddContextDialogProps {
  onAddLink: (link: ContextLink) => Promise<void>;
  onAddObject: (object: ContextObject) => Promise<void>;
  onClose: () => void;
  isSaving: boolean;
}

/**
 * One box for everything a space can take as context. A pasted link or object
 * URL becomes the row to add; anything else searches the sources, so the same
 * palette is where an unconnected source gets connected. Mounted only while
 * open, so its state starts fresh each time.
 */
export function AddContextDialog({
  onAddLink,
  onAddObject,
  onClose,
  isSaving,
}: AddContextDialogProps) {
  const navigate = useNavigate();
  const sources = useContextSources();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<AddContextScope | null>(null);
  const [note, setNote] = useState("");

  const addition = parseAddition(query, scope, sources);

  const submit = async () => {
    if (!addition || isSaving) return;
    const trimmed = note.trim();
    if (addition.kind === "object") {
      await onAddObject({
        ...addition.object,
        title: trimmed || addition.object.title,
      });
    } else {
      await onAddLink({ ...addition.link, note: trimmed });
    }
    onClose();
  };

  const view = buildAddContextView(query, scope, sources, {
    setScope: (next) => {
      setScope(next);
      setQuery("");
    },
    connect: sources.connect,
    openServers: () => {
      onClose();
      void navigate({ to: "/mcp-servers" });
    },
    add: () => void submit(),
  });
  const canAdd = addition !== null && view.blockedBy === null;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className="w-[600px] max-w-[90vw] gap-0 p-0"
        showCloseButton={false}
      >
        <Autocomplete<AddContextSection>
          inline
          defaultOpen
          items={view.sections}
          value={query}
          filter={null}
          autoHighlight
          keepHighlight
          onValueChange={(value, details) => {
            if (typeof value !== "string") return;
            if (details.reason === "input-change") setQuery(value);
          }}
        >
          <AutocompleteInput
            placeholder={
              scope ? scopeHint(scope) : "Paste a link, or search sources…"
            }
            autoFocus
            showClear={query !== ""}
            onKeyDown={(event) => {
              if (event.key === "Backspace" && query === "" && scope) {
                event.preventDefault();
                setScope(null);
              }
            }}
          >
            {scope ? (
              <button
                type="button"
                onClick={() => setScope(null)}
                aria-label={`Remove ${scopeLabel(scope)} filter`}
                className="flex h-5 shrink-0 items-center gap-1 rounded-sm border border-border bg-muted px-1.5 text-foreground text-xxs hover:bg-accent"
              >
                {scope.kind === "source" ? (
                  <ServerIcon
                    iconDomain={scope.state.source.iconDomain}
                    size={12}
                  />
                ) : null}
                {scopeLabel(scope)}
                <XIcon size={10} className="text-muted-foreground" />
              </button>
            ) : null}
          </AutocompleteInput>
          {view.emptyMessage ? (
            <div className="px-6 py-8 text-center text-muted-foreground text-xs">
              {view.emptyMessage}
            </div>
          ) : null}
          <AutocompleteList className="max-h-[55vh]">
            {(section: AddContextSection) => (
              <AutocompleteGroup key={section.label} items={section.items}>
                <AutocompleteLabel>{section.label}</AutocompleteLabel>
                <AutocompleteCollection>
                  {(row: AddContextRow) => (
                    <AutocompleteItem
                      key={row.id}
                      value={row.id}
                      title={row.label}
                      onClick={row.run}
                      className="group flex h-auto! min-h-7 w-full items-center gap-2 py-1.5 pr-2 text-left leading-snug [&>span]:w-full [&>span]:overflow-visible"
                    >
                      <span className="flex size-4 shrink-0 items-center justify-center opacity-80 group-data-highlighted:opacity-100">
                        {row.icon}
                      </span>
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="flex min-h-[18px] items-center gap-2">
                          <span className="min-w-0 flex-1 truncate">
                            {row.label}
                          </span>
                          {row.detail ? (
                            <span className="flex max-w-[40%] shrink-0 items-center gap-1.5 truncate text-[11px] text-muted-foreground">
                              {row.busy ? (
                                <Spinner size="xs" aria-hidden="true" />
                              ) : null}
                              {row.detail}
                            </span>
                          ) : null}
                        </span>
                        {row.subtitle ? (
                          <span
                            className={cn(
                              "truncate text-xxs",
                              row.tone === "warning"
                                ? "text-warning-foreground"
                                : "text-muted-foreground/70",
                            )}
                          >
                            {row.subtitle}
                          </span>
                        ) : null}
                      </span>
                    </AutocompleteItem>
                  )}
                </AutocompleteCollection>
              </AutocompleteGroup>
            )}
          </AutocompleteList>
          {sources.isLoading && !scope && !addition ? (
            <div className="flex items-center gap-2 px-3 py-2 text-muted-foreground text-xs">
              <Spinner size="xs" aria-hidden="true" />
              Loading sources
            </div>
          ) : null}
        </Autocomplete>
        {canAdd ? (
          <div className="flex items-center gap-2 border-border border-t px-3 py-2">
            <Input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder={
                addition.kind === "object"
                  ? "Name (optional)"
                  : "Why it matters (optional)"
              }
              className="h-7 flex-1 text-xs"
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void submit();
                }
              }}
            />
            <Button
              variant="primary"
              size="sm"
              loading={isSaving}
              onClick={() => void submit()}
            >
              Add
            </Button>
          </div>
        ) : null}
        <CommandKeyHints />
      </DialogContent>
    </Dialog>
  );
}
