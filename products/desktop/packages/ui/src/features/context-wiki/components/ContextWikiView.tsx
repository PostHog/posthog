import { BookOpenTextIcon, LockSimpleIcon } from "@phosphor-icons/react";
import { ContextWikiUnavailableError } from "@posthog/api-client/posthog-client";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { FileExplorer } from "@posthog/ui/primitives/FileExplorer";
import {
  PageHeader,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  useContextWikiTree,
  useEnableContextWiki,
} from "../hooks/useContextWiki";
import { buildWikiTree } from "../wikiTree";
import { ContextWikiPagePane, type WikiDraft } from "./ContextWikiPagePane";

/**
 * The organization context wiki explorer: a tree of every wiki page on the
 * left, the selected page (rendered or editable) on the right. Reads and
 * writes go through the same head-guarded pages API agents use, so concurrent
 * edits surface as conflicts instead of overwrites.
 */
export function ContextWikiView({ initialPath }: { initialPath?: string }) {
  // Root-level page: its own header names the view, so the breadcrumb row
  // collapses (same treatment as Command Center).
  useSetHeaderContent(null);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Context</PageHeaderTitle>
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            The shared wiki agents read before they work and update as they
            learn. Pages are markdown files in one organization-wide repo.
          </PageHeaderDescription>
        </PageHeaderHeading>
      </PageHeader>
      <div className="min-h-0 flex-1">
        <ContextWikiBody initialPath={initialPath} />
      </div>
    </div>
  );
}

// The state-dependent body under the constant page header: loading, the two
// distinct empty states (403 dark vs 404 never enabled), errors, or the
// explorer.
function ContextWikiBody({ initialPath }: { initialPath?: string }) {
  const { data: tree, isLoading, error, refetch } = useContextWikiTree();
  const enable = useEnableContextWiki();
  const [selectedPath, setSelectedPath] = useState<string | null>(
    initialPath ?? null,
  );
  // Drafts are keyed by path and held here rather than in the pane, which the
  // explorer remounts on every selection — so switching pages mid-edit, or
  // being moved off a page an agent deleted, no longer destroys the text.
  const [drafts, setDrafts] = useState<Record<string, WikiDraft>>({});

  const setDraft = useCallback((path: string, draft: WikiDraft) => {
    setDrafts((current) => ({ ...current, [path]: draft }));
  }, []);

  const discardDraft = useCallback((path: string) => {
    setDrafts(({ [path]: _discarded, ...rest }) => rest);
  }, []);

  useEffect(() => {
    if (initialPath) {
      setSelectedPath(initialPath);
    }
  }, [initialPath]);

  const wikiRoot = useMemo(
    () => (tree ? buildWikiTree(tree.paths) : null),
    [tree],
  );

  // Fall back to the wiki's entry page (or the first page) when nothing is
  // selected yet, or when the selected page disappeared from the tree.
  const effectivePath = useMemo(() => {
    if (!tree) return null;
    if (selectedPath && tree.paths.includes(selectedPath)) return selectedPath;
    return tree.paths.includes("AGENTS.md")
      ? "AGENTS.md"
      : (tree.paths[0] ?? null);
  }, [tree, selectedPath]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5" />
      </div>
    );
  }

  if (error instanceof ContextWikiUnavailableError) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LockSimpleIcon size={28} />
          </EmptyMedia>
          <EmptyTitle>Context wiki unavailable</EmptyTitle>
          <EmptyDescription>{error.message}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (error) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <BookOpenTextIcon size={28} />
          </EmptyMedia>
          <EmptyTitle>Couldn't load the context wiki</EmptyTitle>
          <EmptyDescription>{error.message}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button variant="outline" size="default" onClick={() => refetch()}>
            Try again
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  if (!wikiRoot) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <BookOpenTextIcon size={28} />
          </EmptyMedia>
          <EmptyTitle>Set up your context wiki</EmptyTitle>
          <EmptyDescription>
            The context wiki is a shared set of markdown pages that agents read
            before they work and update as they learn. Enabling it imports the
            context your spaces already have.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <div className="flex flex-col items-center gap-2">
            <Button
              variant="primary"
              size="default"
              onClick={() => enable.mutate()}
              disabled={enable.isPending}
            >
              {enable.isPending ? <Spinner className="size-4" /> : null}
              Enable context wiki
            </Button>
            {enable.error ? (
              <span className="text-[12px] text-red-11">
                Couldn't enable the wiki: {enable.error.message}
              </span>
            ) : null}
          </div>
        </EmptyContent>
      </Empty>
    );
  }

  return (
    <FileExplorer
      tree={wikiRoot}
      selectedPath={effectivePath}
      onSelectPath={setSelectedPath}
      emptyMessage="The wiki has no pages yet."
      storageKey="context-wiki-explorer"
    >
      {effectivePath ? (
        // Keyed by path so view state never leaks across pages; the draft is
        // held above this so the remount does not take it with it.
        <ContextWikiPagePane
          key={effectivePath}
          path={effectivePath}
          draft={drafts[effectivePath]}
          onDraftChange={setDraft}
          onDraftDiscard={discardDraft}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center text-[13px] text-gray-10">
          The wiki has no pages yet.
        </div>
      )}
    </FileExplorer>
  );
}
