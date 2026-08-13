import { BookOpenIcon, GitBranchIcon, RobotIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { TAGS } from "@posthog/ui/features/prototypes/tags/mockData";
import { useState } from "react";

export function NewTaskDialog({
  open,
  initialTagId,
  onOpenChange,
  onStartTask,
}: {
  open: boolean;
  initialTagId?: string;
  onOpenChange: (open: boolean) => void;
  onStartTask: (title: string, tagIds: string[]) => void;
}) {
  const [title, setTitle] = useState("");
  const [tagIds, setTagIds] = useState<string[]>(
    initialTagId ? [initialTagId] : [],
  );

  const selected = TAGS.filter((t) => tagIds.includes(t.id));
  const repos = [...new Set(selected.flatMap((t) => t.repos))];
  const context = [...new Set(selected.flatMap((t) => t.context))];

  const toggle = (id: string) => {
    setTagIds((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id],
    );
  };

  const start = () => {
    if (!title.trim() || tagIds.length === 0) return;
    onStartTask(title.trim(), tagIds);
    setTitle("");
    setTagIds([]);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New task</DialogTitle>
          <DialogDescription>
            Pick tags to shape what the agent starts with — repos and context
            come from the tags, and stack when you pick more than one.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <input
            className="w-full rounded-md border border-border bg-gray-2 px-3 py-2 text-[13px] text-gray-12 outline-none placeholder:text-gray-9 focus:border-gray-7"
            placeholder="What should the agent do?"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />
          <div className="flex flex-wrap gap-1.5">
            {TAGS.map((tag) => {
              const active = tagIds.includes(tag.id);
              return (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => toggle(tag.id)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] transition-colors",
                    active
                      ? "border-gray-8 bg-gray-4 text-gray-12"
                      : "border-border bg-gray-2 text-gray-10 hover:bg-gray-3",
                  )}
                >
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{ background: `var(--${tag.hue}-9)` }}
                  />
                  {tag.name}
                </button>
              );
            })}
          </div>
          {selected.length > 0 && (
            <div className="rounded-md border border-border bg-gray-2 px-3 py-2 text-[11px] text-gray-10">
              <div className="mb-1 font-semibold text-[10px] text-gray-9 uppercase tracking-wide">
                The agent will start with
              </div>
              <div className="flex items-center gap-1.5">
                <GitBranchIcon size={11} className="shrink-0" />
                <span className="truncate">{repos.join(", ")}</span>
              </div>
              <div className="mt-1 flex items-center gap-1.5">
                <BookOpenIcon size={11} className="shrink-0" />
                <span className="truncate">{context.join(", ")}</span>
              </div>
              <div className="mt-1 flex items-center gap-1.5">
                <RobotIcon size={11} className="shrink-0" />
                <span className="truncate">{selected[0].agentPreset}</span>
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!title.trim() || tagIds.length === 0}
            onClick={start}
          >
            Start agent
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
