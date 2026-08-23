import {
  ContextWikiConflictError,
  ContextWikiLintError,
} from "@posthog/api-client/posthog-client";
import {
  Button,
  cn,
  Spinner,
  Textarea,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { useEffect, useState } from "react";
import {
  useContextWikiPage,
  useContextWikiPageMutation,
} from "../hooks/useContextWiki";

type Mode = "rendered" | "edit";

interface ContextWikiPagePaneProps {
  path: string;
}

/**
 * One wiki page: rendered markdown, or a plain-text editor. Saves send the
 * head the page was loaded at, so a write that races another editor (or an
 * agent's commit) comes back as a conflict banner instead of clobbering.
 */
export function ContextWikiPagePane({ path }: ContextWikiPagePaneProps) {
  const { data: page, isLoading, error, refetch } = useContextWikiPage(path);
  const save = useContextWikiPageMutation();

  const [mode, setMode] = useState<Mode>("rendered");
  const [draft, setDraft] = useState("");
  const [hasDraft, setHasDraft] = useState(false);
  // The head the current draft was seeded from. Pinned once an edit starts so a
  // background refetch (refetchOnWindowFocus fires on app-switch) can't move it
  // under the draft — otherwise a save would adopt the moved head and silently
  // overwrite the concurrent commit instead of coming back as a 409 conflict.
  const [baseHead, setBaseHead] = useState<string | null>(null);

  // Seed the editor from the loaded page, and reseed on refetches, but never
  // over an edit in progress.
  useEffect(() => {
    if (hasDraft) return;
    setDraft(page?.content ?? "");
    setBaseHead(page?.head_sha ?? null);
  }, [page?.content, page?.head_sha, hasDraft]);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="size-5" />
      </div>
    );
  }

  if (error || !page) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 text-[13px] text-gray-10">
        <span>
          {error
            ? `Couldn't load this page: ${error.message}`
            : "This page no longer exists in the wiki."}
        </span>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const onSave = () => {
    save.mutate(
      { path, content: draft, baseHead: baseHead ?? page.head_sha },
      {
        onSuccess: () => {
          setHasDraft(false);
          setMode("rendered");
        },
      },
    );
  };

  const isConflict = save.error instanceof ContextWikiConflictError;
  const lintError =
    save.error instanceof ContextWikiLintError ? save.error : null;

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-b-(--gray-5) px-4 py-2">
        <div className="flex min-w-0 items-center gap-3">
          <ToggleGroup
            value={[mode]}
            onValueChange={(next: string[]) => {
              const selected = next[0];
              if (selected) setMode(selected as Mode);
            }}
            aria-label="Page view mode"
            className="gap-1"
          >
            <ToggleGroupItem value="rendered" size="sm" variant="outline">
              Rendered
            </ToggleGroupItem>
            <ToggleGroupItem value="edit" size="sm" variant="outline">
              Edit
            </ToggleGroupItem>
          </ToggleGroup>
          {/* The page's location inside the wiki repo, for agents and deep
              links: this is the path harnesses see under the mounted wiki. */}
          <code className="truncate text-[12px] text-gray-10">{path}</code>
        </div>
        {mode === "edit" ? (
          <div className="flex shrink-0 items-center gap-2">
            {hasDraft ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setDraft(page.content);
                  setHasDraft(false);
                  save.reset();
                }}
                disabled={save.isPending}
              >
                Discard
              </Button>
            ) : null}
            <Button
              variant="primary"
              size="sm"
              onClick={onSave}
              disabled={save.isPending || !hasDraft}
            >
              {save.isPending ? <Spinner className="size-3.5" /> : null}
              Save
            </Button>
          </div>
        ) : null}
      </div>

      {save.error ? (
        <div
          className={cn(
            "mx-4 mt-3 rounded-(--radius-2) border px-3 py-2 text-[12px]",
            isConflict
              ? "border-(--amber-6) bg-(--amber-2) text-(--amber-11)"
              : "border-(--red-6) bg-(--red-2) text-(--red-11)",
          )}
        >
          {isConflict ? (
            <div className="flex items-center justify-between gap-3">
              <span>
                This page changed while you were editing. Load the latest
                version, then reapply your edits.
              </span>
              <Button
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => {
                  save.reset();
                  setHasDraft(false);
                  void refetch();
                }}
              >
                Load latest
              </Button>
            </div>
          ) : lintError ? (
            <div className="flex flex-col gap-1">
              <span>{lintError.message}</span>
              {lintError.errors.length > 0 ? (
                <ul className="list-disc pl-4">
                  {lintError.errors.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : (
            <span>Couldn't save this page: {save.error.message}</span>
          )}
        </div>
      ) : null}

      {mode === "edit" ? (
        <div className="flex min-h-0 flex-1 p-4">
          <Textarea
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setHasDraft(true);
            }}
            // Locked while the write is in flight: a successful save reseeds the
            // draft from the saved content, so anything typed during the window
            // would be silently discarded on success.
            disabled={save.isPending}
            placeholder="Write markdown for this page…"
            className="min-h-0 flex-1 resize-none font-mono text-[13px]"
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="p-4 text-[13px]">
            <MarkdownRenderer content={page.content} />
          </div>
        </div>
      )}
    </div>
  );
}
