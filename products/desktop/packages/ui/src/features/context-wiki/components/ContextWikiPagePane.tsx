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
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { useState } from "react";
import type { Components } from "react-markdown";
import {
  useContextWikiPage,
  useContextWikiPageMutation,
} from "../hooks/useContextWiki";

type Mode = "rendered" | "edit";

/** An unsaved edit, plus the head it is based on. */
export interface WikiDraft {
  content: string;
  baseHead: string | null;
}

interface ContextWikiPagePaneProps {
  path: string;
  /**
   * Drafts can be held above the pane so they survive it unmounting — the
   * explorer keys the pane by path, so a page switch would otherwise destroy
   * one. Omit all three and the pane keeps its own draft instead.
   */
  draft?: WikiDraft;
  onDraftChange?: (path: string, draft: WikiDraft) => void;
  onDraftDiscard?: (path: string) => void;
}

// The draft lives above the pane when the caller manages it, and inside
// otherwise. `useState` runs either way, so the branch is safe.
function useDraft(
  external: WikiDraft | undefined,
  onChange: ContextWikiPagePaneProps["onDraftChange"],
  onDiscard: ContextWikiPagePaneProps["onDraftDiscard"],
): [
  WikiDraft | undefined,
  (path: string, draft: WikiDraft) => void,
  (path: string) => void,
] {
  const [internal, setInternal] = useState<WikiDraft | undefined>(undefined);
  if (onChange && onDiscard) {
    return [external, onChange, onDiscard];
  }
  return [
    internal,
    (_path, draft) => setInternal(draft),
    () => setInternal(undefined),
  ];
}

// Wiki pages are org-shared and agent-writable, so their markdown is untrusted.
// A remote <img> would make every viewer's machine issue a GET to an
// author-chosen URL, which is a tracking beacon or an internal-network probe.
// Block images the way ChatMarkdown does; there is no wiki image-upload path,
// so nothing legitimate is lost.
const wikiMarkdownComponents: Partial<Components> = {
  img: ({ alt }) => (
    <span className="text-[13px] text-gray-10">
      Remote image blocked{alt ? `: ${alt}` : ""}
    </span>
  ),
};

/**
 * One wiki page: rendered markdown, or a plain-text editor. Saves send the
 * head the page was loaded at, so a write that races another editor (or an
 * agent's commit) comes back as a conflict banner instead of clobbering.
 */
export function ContextWikiPagePane({
  path,
  draft: externalDraft,
  onDraftChange,
  onDraftDiscard,
}: ContextWikiPagePaneProps) {
  const { data: page, isLoading, error, refetch } = useContextWikiPage(path);
  const save = useContextWikiPageMutation();

  // Reopen straight into the editor when this page already has a draft, so
  // coming back to it shows the unsaved text rather than the saved page.
  const [mode, setMode] = useState<Mode>(externalDraft ? "edit" : "rendered");
  const [draft, setDraft, discardDraft] = useDraft(
    externalDraft,
    onDraftChange,
    onDraftDiscard,
  );

  // A draft carries the head it was based on. Pinned at the first keystroke so a
  // background refetch (refetchOnWindowFocus fires on app-switch) can't move it
  // under the draft — otherwise a save would adopt the moved head and silently
  // overwrite the concurrent commit instead of coming back as a 409 conflict.
  const hasDraft = draft !== undefined;
  const content = draft?.content ?? page?.content ?? "";
  const baseHead = draft?.baseHead ?? page?.head_sha ?? null;

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

  const commit = (against: string | null) => {
    save.mutate(
      { path, content, baseHead: against ?? page.head_sha },
      {
        onSuccess: () => {
          discardDraft(path);
          setMode("rendered");
        },
        // Pull the page the other writer landed so the Rendered tab shows what
        // the draft is now up against. The draft itself is left alone.
        onError: () => void refetch(),
      },
    );
  };

  const conflict =
    save.error instanceof ContextWikiConflictError ? save.error : null;
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
          <span className="flex shrink-0 items-center gap-1 text-[11px] text-gray-10">
            Updated <RelativeTimestamp timestamp={page.updated_at} />
          </span>
        </div>
        {mode === "edit" ? (
          <div className="flex shrink-0 items-center gap-2">
            {hasDraft ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  discardDraft(path);
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
              onClick={() => commit(baseHead)}
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
            conflict
              ? "border-(--amber-6) bg-(--amber-2) text-(--amber-11)"
              : "border-(--red-6) bg-(--red-2) text-(--red-11)",
          )}
        >
          {conflict ? (
            <div className="flex items-center justify-between gap-3">
              <span>
                Someone else changed this page while you were editing. Your
                edits are still here — switch to Rendered to read their version.
              </span>
              <div className="flex shrink-0 items-center gap-2">
                {/* Both ways out are explicit: nothing throws the draft away
                    on the user's behalf. */}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    discardDraft(path);
                    save.reset();
                  }}
                  disabled={save.isPending}
                >
                  Discard mine
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => commit(conflict.currentHead)}
                  disabled={save.isPending}
                >
                  Save mine anyway
                </Button>
              </div>
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
            value={content}
            onChange={(e) =>
              setDraft(path, { content: e.target.value, baseHead })
            }
            // Locked while the write is in flight: a successful save drops the
            // draft, so anything typed during the window would be lost.
            disabled={save.isPending}
            placeholder="Write markdown for this page…"
            className="min-h-0 flex-1 resize-none font-mono text-[13px]"
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="p-4 text-[13px]">
            <MarkdownRenderer
              content={page.content}
              componentsOverride={wikiMarkdownComponents}
            />
          </div>
        </div>
      )}
    </div>
  );
}
