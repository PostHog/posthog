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
import {
  joinPageContent,
  splitPageContent,
  stripFrontmatter,
} from "@posthog/ui/features/context-wiki/pageContent";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { useState } from "react";
import type { Components } from "react-markdown";
import {
  useContextWikiPage,
  useContextWikiPageMutation,
} from "../hooks/useContextWiki";
import "./wikiProse.css";

type Mode = "rendered" | "edit";

/**
 * `pane` fills the wiki explorer: its own toolbar, its own scroll.
 * `inline` is a section of a longer page, so it brings a section heading and no
 * scroll of its own.
 */
type Layout = "pane" | "inline";

/** An unsaved edit, plus the head it is based on. */
export interface WikiDraft {
  content: string;
  baseHead: string | null;
}

interface ContextWikiPagePaneProps {
  path: string;
  layout?: Layout;
  /** Inline only: the heading above the page. */
  title?: string;
  /** Inline only: offered beside the page's location. */
  onOpenInWiki?: () => void;
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
const blockedImage: Partial<Components> = {
  img: ({ alt }) => (
    <span className="text-[13px] text-gray-10">
      Remote image blocked{alt ? `: ${alt}` : ""}
    </span>
  ),
};

// MarkdownRenderer dresses markdown for a chat message: headings become small
// accent-colored paragraphs. A page of notes reads as a page, so the elements
// stay plain and `.wiki-prose` sizes them.
const proseMarkdownComponents: Partial<Components> = {
  ...blockedImage,
  h1: ({ children }) => <h1>{children}</h1>,
  h2: ({ children }) => <h2>{children}</h2>,
  h3: ({ children }) => <h3>{children}</h3>,
  h4: ({ children }) => <h4>{children}</h4>,
  p: ({ children }) => <p>{children}</p>,
  ul: ({ children }) => <ul>{children}</ul>,
  ol: ({ children }) => <ol>{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  blockquote: ({ children }) => <blockquote>{children}</blockquote>,
  hr: () => <hr />,
};

/**
 * One wiki page: rendered markdown, or a plain-text editor. Saves send the
 * head the page was loaded at, so a write that races another editor (or an
 * agent's commit) comes back as a conflict banner instead of clobbering.
 */
export function ContextWikiPagePane({
  path,
  layout = "pane",
  title,
  onOpenInWiki,
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

  const inline = layout === "inline";

  // A draft carries the head it was based on. Pinned at the first keystroke so a
  // background refetch (refetchOnWindowFocus fires on app-switch) can't move it
  // under the draft — otherwise a save would adopt the moved head and silently
  // overwrite the concurrent commit instead of coming back as a 409 conflict.
  const hasDraft = draft !== undefined;
  // Inline drafts hold the notes alone; the frontmatter and the page's heading
  // are the repo's, and go back on at save time.
  const parts = splitPageContent(page?.content ?? "");
  const edited =
    draft?.content ?? (inline ? parts.body : (page?.content ?? ""));
  const content = inline ? joinPageContent(parts.preamble, edited) : edited;
  const baseHead = draft?.baseHead ?? page?.head_sha ?? null;

  if (isLoading) {
    return (
      <div
        className={cn(
          "flex items-center justify-center",
          inline ? "py-10" : "flex-1",
        )}
      >
        <Spinner className="size-5" />
      </div>
    );
  }

  if (error || !page) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center gap-2 text-[13px] text-gray-10",
          inline ? "py-10" : "flex-1",
        )}
      >
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

  const cancelEdit = () => {
    discardDraft(path);
    save.reset();
    setMode("rendered");
  };

  const conflict =
    save.error instanceof ContextWikiConflictError ? save.error : null;
  const lintError =
    save.error instanceof ContextWikiLintError ? save.error : null;

  const errorBanner = save.error ? (
    <div
      className={cn(
        "rounded-(--radius-2) border px-3 py-2 text-[12px]",
        inline ? "mt-3" : "mx-4 mt-3",
        conflict
          ? "border-(--amber-6) bg-(--amber-2) text-(--amber-11)"
          : "border-(--red-6) bg-(--red-2) text-(--red-11)",
      )}
    >
      {conflict ? (
        <div className="flex items-center justify-between gap-3">
          <span>
            Someone else changed this page while you were editing. Your edits
            are still here, so pick which version the page keeps.
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
  ) : null;

  const body = stripFrontmatter(page.content);
  const rendered = (source: string) => (
    <div className={inline ? "wiki-prose wiki-prose--nested" : "wiki-prose"}>
      <MarkdownRenderer
        content={source}
        componentsOverride={proseMarkdownComponents}
      />
    </div>
  );

  if (inline) {
    // The page's own title is the section heading above, so the body starts at
    // what the space actually wrote.
    const inlineBody = parts.body;
    return (
      <section>
        <div className="flex items-center justify-between gap-3 border-(--gray-4) border-b pb-2.5">
          <div className="flex min-w-0 items-baseline gap-2.5">
            <h2 className="shrink-0 font-semibold text-(--gray-12) text-[15px] tracking-[-0.008em]">
              {title ?? "Notes"}
            </h2>
            {/* Where the notes live and when they moved: the facts an agent or a
                deep link needs, said once beside the heading rather than as a
                footer under a page of prose. */}
            <span className="flex min-w-0 items-baseline gap-1.5 text-(--gray-9) text-[11.5px]">
              <code className="truncate">{path}</code>
              <span aria-hidden>·</span>
              <span className="shrink-0">
                updated <RelativeTimestamp timestamp={page.updated_at} />
              </span>
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {onOpenInWiki && mode !== "edit" ? (
              <Button variant="default" size="sm" onClick={onOpenInWiki}>
                Open in wiki
              </Button>
            ) : null}
            {mode === "edit" ? (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={cancelEdit}
                  disabled={save.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  loading={save.isPending}
                  onClick={() => commit(baseHead)}
                  disabled={save.isPending || !hasDraft}
                >
                  Save
                </Button>
              </>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setMode("edit")}
              >
                Edit
              </Button>
            )}
          </div>
        </div>

        {errorBanner}

        <div className="pt-4">
          {mode === "edit" ? (
            // The notes are edited where they are read, in the page's own type:
            // markdown, but on the same measure and rhythm as the prose above.
            <Textarea
              value={edited}
              onChange={(e) =>
                setDraft(path, { content: e.target.value, baseHead })
              }
              // Locked while the write is in flight: a successful save drops the
              // draft, so anything typed during the window would be lost.
              disabled={save.isPending}
              autoFocus
              placeholder="Write the notes in markdown…"
              className="wiki-prose wiki-prose--edit min-h-[24rem] resize-none border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
            />
          ) : inlineBody ? (
            rendered(inlineBody)
          ) : (
            <p className="max-w-[32rem] text-(--gray-10) text-[14px] leading-relaxed">
              Nothing written yet. Notes tell every agent the conventions, the
              key files, and anything else the code does not say on its own.
            </p>
          )}
        </div>
      </section>
    );
  }

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

      {errorBanner}

      {mode === "edit" ? (
        <div className="flex min-h-0 flex-1 p-4">
          <Textarea
            value={edited}
            onChange={(e) =>
              setDraft(path, { content: e.target.value, baseHead })
            }
            disabled={save.isPending}
            placeholder="Write markdown for this page…"
            className="min-h-0 flex-1 resize-none font-mono text-[13px]"
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[46rem] px-6 py-6">
            {rendered(body)}
          </div>
        </div>
      )}
    </div>
  );
}
