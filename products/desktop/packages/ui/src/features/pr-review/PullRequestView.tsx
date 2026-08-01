import {
  ArrowSquareOutIcon,
  GitPullRequestIcon,
  TextAlignLeftIcon,
} from "@phosphor-icons/react";
import { parseGithubUrl } from "@posthog/git/utils";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { useMemo } from "react";
import { openExternalUrl } from "../../shell/openExternal";
import { PrChecksSection } from "./PrChecksSection";
import { PrCommentsSection } from "./PrCommentsSection";
import { PrFilesChangedSection } from "./PrFilesChangedSection";
import { PrReviewActions } from "./PrReviewActions";
import { usePrInfo } from "./usePrInfo";

interface PullRequestViewProps {
  prUrl: string;
}

/**
 * Native, full-page pull request view: description, files changed (with
 * GitHub-style "Viewed" tracking) and approve/merge actions — no browser
 * round-trip. Opened from the sidebar's PR badge.
 */
export function PullRequestView({ prUrl }: PullRequestViewProps) {
  const prRef = useMemo(() => (prUrl ? parseGithubUrl(prUrl) : null), [prUrl]);
  const isPr = prRef?.kind === "pr";
  const infoQuery = usePrInfo(isPr ? prUrl : null);
  const info = infoQuery.data;

  if (!isPr) {
    return (
      <div className="flex h-full items-center justify-center">
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <GitPullRequestIcon />
            </EmptyMedia>
            <EmptyTitle>No pull request</EmptyTitle>
            <EmptyDescription>
              This link doesn't point to a GitHub pull request.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[100ch] flex-col gap-5 px-6 py-5 text-[13px]">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <GitPullRequestIcon size={14} className="shrink-0 text-gray-11" />
            <span className="font-mono text-[12px] text-gray-11">
              {prRef.owner}/{prRef.repo}#{prRef.number}
            </span>
            {info && (
              <PrStateBadge
                state={info.state}
                merged={info.merged}
                draft={info.draft}
              />
            )}
          </div>
          <div className="flex items-start justify-between gap-3">
            <h1 className="min-w-0 font-semibold text-[20px] text-gray-12 leading-snug tracking-[-0.01em]">
              {info ? (
                info.title
              ) : (
                <span className="inline-flex items-center gap-2 text-gray-10">
                  <Spinner />
                  Loading pull request…
                </span>
              )}
            </h1>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => openExternalUrl(prUrl)}
              className="shrink-0 gap-2"
            >
              Open in GitHub
              <ArrowSquareOutIcon size={12} />
            </Button>
          </div>
          {info && (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-gray-11">
              {info.author && <span>{info.author}</span>}
              {info.baseRefName && info.headRefName && (
                <>
                  <span className="text-(--gray-8)">·</span>
                  <span className="font-mono">
                    {info.headRefName} → {info.baseRefName}
                  </span>
                </>
              )}
              <span className="text-(--gray-8)">·</span>
              <span className="font-mono tabular-nums">
                <span className="text-(--green-9)">+{info.additions}</span>{" "}
                <span className="text-(--red-9)">−{info.deletions}</span>
              </span>
            </div>
          )}
        </div>

        <DetailSection Icon={TextAlignLeftIcon} title="Description">
          {info?.body.trim() ? (
            <div className="min-w-0 max-w-[80ch] text-pretty break-words text-[13px] text-gray-11 [&_*]:leading-relaxed [&_.rt-Text]:mb-2 [&_li]:mb-1 [&_p:last-child]:mb-0">
              <MarkdownRenderer content={info.body} />
            </div>
          ) : (
            <div className="py-1 text-[12px] text-gray-10 italic">
              No description provided.
            </div>
          )}
        </DetailSection>

        <PrFilesChangedSection prUrl={prUrl} />

        <PrCommentsSection prUrl={prUrl} />

        <PrChecksSection prUrl={prUrl} />

        <PrReviewActions prUrl={prUrl} />
      </div>
    </div>
  );
}

function PrStateBadge({
  state,
  merged,
  draft,
}: {
  state: string;
  merged: boolean;
  draft: boolean;
}) {
  const { label, className } = merged
    ? { label: "Merged", className: "bg-(--purple-3) text-(--purple-11)" }
    : state.toLowerCase() === "closed"
      ? { label: "Closed", className: "bg-(--red-3) text-(--red-11)" }
      : draft
        ? { label: "Draft", className: "bg-(--gray-3) text-(--gray-11)" }
        : { label: "Open", className: "bg-(--green-3) text-(--green-11)" };

  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 font-medium text-[11px] ${className}`}
    >
      {label}
    </span>
  );
}
