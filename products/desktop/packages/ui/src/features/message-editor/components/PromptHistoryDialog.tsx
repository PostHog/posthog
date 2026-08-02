import { ClockCounterClockwise, MagnifyingGlass } from "@phosphor-icons/react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
  Input,
  InputGroupButton,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { formatRelativeTimeLong } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useTaskInputHistoryStore } from "@posthog/ui/features/message-editor/taskInputHistoryStore";
import { track } from "@posthog/ui/shell/analytics";
import { showMessageBox } from "@posthog/ui/utils/dialog";
import Fuse from "fuse.js";
import { useMemo, useRef, useState } from "react";

const COLLAPSED_LIMIT = 180;

interface PromptHistoryDialogProps {
  onSelect: (text: string) => void;
  hasPendingDraft: () => boolean;
  disabled?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function PromptHistoryDialog({
  onSelect,
  hasPendingDraft,
  disabled,
  onOpenChange,
}: PromptHistoryDialogProps) {
  const entries = useTaskInputHistoryStore((s) => s.entries);
  const hasHistory = entries.length > 0;
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    onOpenChange?.(next);
    if (next) {
      // Reset transient state when re-opening so the dialog starts fresh,
      // but leave it untouched during the close animation to avoid flashing
      // the unfiltered list before the popup unmounts.
      setExpanded(new Set());
      setQuery("");
      track(ANALYTICS_EVENTS.PROMPT_HISTORY_OPENED, {
        entry_count: entries.length,
      });
    }
  };

  const applySelection = (text: string, draftWasPending: boolean) => {
    const entry = entries.find((e) => e.text === text);
    track(ANALYTICS_EVENTS.PROMPT_HISTORY_SELECTED, {
      entry_count: entries.length,
      entry_age_seconds: entry?.createdAt
        ? Math.round((Date.now() - entry.createdAt) / 1000)
        : null,
      had_pending_draft: draftWasPending,
      had_search_query: query.trim().length > 0,
      prompt_length: text.length,
    });
    handleOpenChange(false);
    onSelect(text);
  };

  const handleEntryClick = async (text: string) => {
    if (hasPendingDraft()) {
      const result = await showMessageBox({
        type: "warning",
        title: "Replace draft?",
        message: "Replace draft with this prompt?",
        detail:
          "Loading this prompt will overwrite the text currently in the editor.",
        buttons: ["Cancel", "Replace"],
        defaultId: 1,
        cancelId: 0,
      });
      if (result.response !== 1) return;
      applySelection(text, true);
      return;
    }
    applySelection(text, false);
  };

  const toggleExpanded = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const reversed = useMemo(() => [...entries].reverse(), [entries]);
  const fuse = useMemo(
    () =>
      new Fuse(reversed, {
        keys: ["text"],
        threshold: 0.4,
        ignoreLocation: true,
      }),
    [reversed],
  );
  const filtered = useMemo(() => {
    const q = query.trim();
    if (!q) return reversed;
    return fuse.search(q).map((r) => r.item);
  }, [fuse, reversed, query]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <TooltipProvider delay={500}>
        <Tooltip>
          <DialogTrigger
            render={
              <TooltipTrigger
                render={
                  <InputGroupButton
                    variant="default"
                    size="icon-sm"
                    aria-label="Prompt history"
                    disabled={disabled || !hasHistory}
                  >
                    <ClockCounterClockwise size={14} />
                  </InputGroupButton>
                }
              />
            }
          />
          <TooltipContent>
            {hasHistory ? "Prompt history" : "No prompts yet"}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <DialogContent
        showCloseButton={false}
        initialFocus={searchRef}
        onClick={(e) => e.stopPropagation()}
        className="w-[min(760px,calc(100vw-32px))] max-w-[760px] pt-3 pb-0 sm:max-w-[760px]"
      >
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-2 px-3">
            <div className="flex items-center gap-2">
              <ClockCounterClockwise size={14} />
              <DialogTitle className="font-medium text-sm">
                Prompt history
              </DialogTitle>
            </div>
            <div className="relative">
              <MagnifyingGlass
                size={13}
                className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2 text-(--gray-9)"
              />
              <Input
                ref={searchRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search prompts…"
                className="pl-7"
              />
            </div>
          </div>

          <div className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto pb-3 pl-3">
            {filtered.length === 0 && (
              <div className="px-1 py-3 text-(--gray-10) text-[13px]">
                No matching prompts.
              </div>
            )}
            {filtered.map((entry) => {
              const key = `${entry.createdAt}-${entry.text}`;
              const isExpanded = expanded.has(key);
              const stamp =
                entry.createdAt != null
                  ? formatRelativeTimeLong(entry.createdAt)
                  : null;
              const tooLong = entry.text.length > COLLAPSED_LIMIT;
              const display =
                tooLong && !isExpanded
                  ? `${entry.text.slice(0, COLLAPSED_LIMIT).trimEnd()}…`
                  : entry.text;

              return (
                // biome-ignore lint/a11y/useSemanticElements: cannot nest the inline "Read more" <button> inside a real <button>
                <div
                  key={key}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleEntryClick(entry.text)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      handleEntryClick(entry.text);
                    }
                  }}
                  className="mr-3 cursor-pointer rounded-(--radius-2) border border-(--gray-6) bg-(--gray-2) px-2 py-2 transition-colors hover:border-(--gray-7) hover:bg-(--gray-3) focus-visible:border-(--accent-7) focus-visible:bg-(--gray-3) focus-visible:outline-none"
                >
                  {stamp && (
                    <span className="block pb-1 text-(--gray-9) text-[11px] uppercase tracking-wide">
                      {stamp}
                    </span>
                  )}
                  <span className="whitespace-pre-wrap text-(--gray-12) text-[13px]">
                    {display}
                    {tooLong && (
                      <>
                        {" "}
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpanded(key);
                          }}
                          className="rounded-(--radius-1) bg-(--accent-3) px-1 font-medium text-(--accent-11) hover:bg-(--accent-4) hover:text-(--accent-12)"
                        >
                          {isExpanded ? "Read less" : "Read more"}
                        </button>
                      </>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
