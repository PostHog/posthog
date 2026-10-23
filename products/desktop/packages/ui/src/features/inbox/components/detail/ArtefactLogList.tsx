import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  CaretRightIcon,
  InfoIcon,
} from "@phosphor-icons/react";
import { attributionLabel } from "@posthog/core/inbox/activityLog";
import {
  formatRankingLift,
  formatRankingProbability,
  rankingLiftBarPercent,
} from "@posthog/core/inbox/rankingFormat";
import { Badge } from "@posthog/quill";
import { dismissalReasonLabel } from "@posthog/shared/dismissalReasons";
import type {
  ActionabilityJudgmentContent,
  AnySignalReportArtefact,
  CodeReferenceContent,
  CommitContent,
  DismissalContent,
  LineReferenceContent,
  NoteContent,
  PriorityJudgmentContent,
  RankingHead,
  RankingModelResult,
  RankingScoreContent,
  SafetyJudgmentContent,
  SignalFindingContent,
  SignalReportArtefactContent,
  SuggestedReviewer,
  TaskRunArtefactContent,
  WorkClaimContent,
  WorkReleaseContent,
} from "@posthog/shared/types";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { ArtefactCommit } from "@posthog/ui/features/inbox/components/detail/ArtefactCommit";
import { ArtefactTaskRun } from "@posthog/ui/features/inbox/components/detail/ArtefactTaskRun";
import { SignalReportActionabilityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportActionabilityBadge";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { cachedImageUrl } from "@posthog/ui/shell/cachedImageUrl";
import { Fragment, useState } from "react";

// A chronological log of every artefact on a report. Each known type renders a
// tailored body; unrecognized types fall back to a plain text preview (never raw
// JSON). Timeline chrome (rails, grouping) is a follow-up — this is the polished
// content layer.

// Each entry is framed as a point-in-time action ("what happened"), since the log is an
// append-only history of changes — the current status lives at the top of the report.
const TYPE_LABELS: Record<string, string> = {
  code_reference: "Code referenced",
  line_reference: "Line highlighted",
  commit: "Commit pushed",
  task_run: "Task run",
  note: "Note added",
  priority_judgment: "Priority assessed",
  actionability_judgment: "Actionability assessed",
  safety_judgment: "Safety assessed",
  signal_finding: "Signal investigated",
  suggested_reviewers: "Reviewers suggested",
  repo_selection: "Repo selected",
  dismissal: "Report feedback added",
  video_segment: "Video segment",
  ranking_score: "Ranking scored",
  work_claim: "Work claimed",
  work_release: "Work released",
};

const WORK_RELEASE_REASON_LABELS: Record<WorkReleaseContent["reason"], string> =
  {
    released: "Released",
    taken_over: "Taken over",
  };

function typeLabel(artefact: AnySignalReportArtefact): string {
  if (artefact.type === "dismissal") {
    const state = (artefact.content as DismissalContent).state;
    return state === "resolved"
      ? "Report resolved"
      : state === "suppressed"
        ? "Report dismissed"
        : state === "potential"
          ? "Report snoozed"
          : "Report feedback added";
  }
  return TYPE_LABELS[artefact.type] ?? artefact.type;
}

function prettify(value: string): string {
  const cleaned = value.replace(/[-_]/g, " ").trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

/** Map a file path to a syntax-highlight language key (extension-based). */
function languageFromPath(filePath: string): string {
  return filePath.split(".").pop()?.toLowerCase() ?? "";
}

/**
 * Who produced the artefact: a user's name, "agent" for task-attributed writes,
 * or null for system (pipeline) writes and pre-attribution rows.
 */
// The generic `SignalReportArtefact` fallback carries `type: string`, so it stays
// in every narrowed branch and breaks discriminated-union narrowing — the runtime
// `type` dispatch is authoritative (content is set alongside type in the
// normalizers), so we read `content` through the matching content type.

/** Short, monospace location shown next to the type label (file path / span). */
function locationLabel(artefact: AnySignalReportArtefact): string | null {
  switch (artefact.type) {
    case "code_reference": {
      const c = artefact.content as CodeReferenceContent;
      return `${c.file_path}:${c.start_line}-${c.end_line}`;
    }
    case "line_reference": {
      const c = artefact.content as LineReferenceContent;
      return `${c.file_path}:${c.line}`;
    }
    default:
      return null;
  }
}

function CodeRefBlock({ code, language }: { code: string; language: string }) {
  return (
    <div className="mt-1.5">
      <CodeBlock size="1">
        <HighlightedCode code={code} language={language} />
      </CodeBlock>
    </div>
  );
}

function RelevanceNote({ note }: { note: string }) {
  if (!note.trim()) return null;
  return <span className="block text-(--gray-11) text-[13px]">{note}</span>;
}

/** Judgment explanations are often paragraphs — collapsed by default behind a toggle. */
function CollapsibleReasoning({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  if (!text.trim()) return null;
  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="-mx-1 flex items-center gap-1 rounded-md px-1 py-0.5 text-(--gray-11) text-[13px] transition-colors hover:bg-(--gray-3) hover:text-(--gray-12)"
      >
        {expanded ? (
          <CaretDownIcon size={12} className="shrink-0" />
        ) : (
          <CaretRightIcon size={12} className="shrink-0" />
        )}
        {expanded ? "Hide reasoning" : "Show reasoning"}
      </button>
      {expanded ? (
        <span className="block text-(--gray-11) text-[13px]">{text}</span>
      ) : null}
    </div>
  );
}

/**
 * Notes are free-form markdown and can run long — collapsed to a one-line
 * preview (the first non-empty line) that expands to the rendered note.
 */
function CollapsibleNote({
  note,
  author,
}: {
  note: string;
  author?: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const preview = note
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="-mx-1 flex w-full items-center gap-1 rounded-md px-1 py-0.5 text-left text-(--gray-11) text-[13px] transition-colors hover:bg-(--gray-3) hover:text-(--gray-12)"
      >
        {expanded ? (
          <CaretDownIcon size={12} className="shrink-0" />
        ) : (
          <CaretRightIcon size={12} className="shrink-0" />
        )}
        {expanded ? (
          "Hide note"
        ) : (
          <span className="min-w-0 flex-1 truncate">{preview ?? "Note"}</span>
        )}
      </button>
      {expanded ? (
        <div className="text-[13px]">
          <MarkdownRenderer content={note} />
          {author ? (
            <span className="block text-(--gray-10) text-[12px]">
              — {author}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ReviewersBody({ reviewers }: { reviewers: SuggestedReviewer[] }) {
  if (reviewers.length === 0) {
    return (
      <span className="block text-(--gray-10) text-[13px]">
        No reviewers assigned.
      </span>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      {reviewers.map((reviewer) => (
        <div
          key={
            reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login
          }
          className="flex flex-wrap items-center gap-2"
        >
          {reviewer.github_login ? (
            <img
              src={cachedImageUrl(
                `https://github.com/${reviewer.github_login}.png?size=28`,
              )}
              alt=""
              className="github-avatar h-[18px] w-[18px] shrink-0 rounded-full"
              onLoad={(e) => e.currentTarget.classList.add("loaded")}
            />
          ) : null}
          <span className="text-[13px]">
            {reviewer.user?.first_name ||
              reviewer.github_name ||
              reviewer.github_login ||
              reviewer.user?.email ||
              "Unknown reviewer"}
          </span>
          {reviewer.github_login ? (
            <a
              href={`https://github.com/${reviewer.github_login}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-0.5 text-[12px] text-gray-9 hover:text-gray-11"
            >
              @{reviewer.github_login}
              <ArrowSquareOutIcon size={10} />
            </a>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function RankingLiftBar({ head }: { head: RankingHead }) {
  return (
    <div className="relative h-1.5 overflow-hidden rounded-full bg-(--gray-4)">
      {head.lift !== null ? (
        <div
          className={`h-full rounded-full ${head.readable ? "bg-(--accent-9)" : "bg-(--gray-8)"}`}
          style={{ width: `${rankingLiftBarPercent(head.lift)}%` }}
        />
      ) : null}
      <span
        className="absolute inset-y-0 left-1/2 w-px bg-(--gray-9)"
        aria-hidden
      />
    </div>
  );
}

function RankingHeadRows({ heads }: { heads: RankingHead[] }) {
  return (
    <div className="grid grid-cols-[minmax(0,max-content)_minmax(2rem,10rem)_auto_auto] items-center justify-start gap-x-2 gap-y-1 text-[12px]">
      {heads.map((head) => {
        const tone = head.readable ? "text-(--gray-12)" : "text-(--gray-10)";
        return (
          <Fragment key={head.name}>
            <span className={`truncate ${tone}`}>{prettify(head.name)}</span>
            <RankingLiftBar head={head} />
            <span className={`text-right tabular-nums ${tone}`}>
              {head.lift !== null ? formatRankingLift(head.lift) : null}
            </span>
            <div className="flex items-center justify-end gap-1 text-(--gray-10) tabular-nums">
              {formatRankingProbability(head.probability)}
              {head.readable ? (
                <span className="size-3" aria-hidden />
              ) : (
                <span
                  role="img"
                  title="No holdout read for this head yet"
                  aria-label="No holdout read for this head yet"
                  className="inline-flex"
                >
                  <InfoIcon size={12} />
                </span>
              )}
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}

function RankingModelBody({ model }: { model: RankingModelResult }) {
  if (model.status === "skipped" || model.heads.length === 0) {
    return (
      <span className="block text-(--gray-10) text-[12px]">
        Skipped{model.skip_reason ? `: ${model.skip_reason}` : ""}
      </span>
    );
  }
  return <RankingHeadRows heads={model.heads} />;
}

function RankingScoreBody({ content }: { content: RankingScoreContent }) {
  const [showOthers, setShowOthers] = useState(false);
  const { served, challengers } = content;
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <RankingModelBody model={served} />
      <div className="flex flex-wrap items-center gap-1 text-(--gray-10) text-[12px]">
        <span className="break-all font-mono">{served.key}</span>
        {content.manifest_version ? (
          <span>· manifest {content.manifest_version}</span>
        ) : null}
        {content.scored_at ? (
          <>
            <span>·</span>
            <RelativeTimestamp timestamp={content.scored_at} />
          </>
        ) : null}
      </div>
      {challengers.length > 0 ? (
        <div>
          <button
            type="button"
            onClick={() => setShowOthers((v) => !v)}
            aria-expanded={showOthers}
            className="-mx-1 flex items-center gap-1 rounded-md px-1 py-0.5 text-(--gray-11) text-[13px] transition-colors hover:bg-(--gray-3) hover:text-(--gray-12)"
          >
            {showOthers ? (
              <CaretDownIcon size={12} className="shrink-0" />
            ) : (
              <CaretRightIcon size={12} className="shrink-0" />
            )}
            Other models ({challengers.length})
          </button>
          {showOthers ? (
            <div className="mt-2 flex flex-col gap-3 pl-3">
              {challengers.map((model) => {
                const role = model.roles.find((r) => r !== "served");
                return (
                  <div key={model.key} className="flex min-w-0 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="break-all font-mono text-(--gray-11) text-[12px]">
                        {model.key}
                      </span>
                      {role ? (
                        <Badge variant="default">{prettify(role)}</Badge>
                      ) : null}
                    </div>
                    <RankingModelBody model={model} />
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ArtefactBody({
  reportId,
  artefact,
  hideCommitDiffs,
}: {
  reportId: string;
  artefact: AnySignalReportArtefact;
  hideCommitDiffs?: boolean;
}) {
  // Degraded rows carry a plain text preview instead of their type's content
  // shape — render that rather than feeding mismatched content to a typed body.
  if (artefact.degraded) {
    // A score has no text, so its preview would be a JSON dump. Show only the label.
    if (artefact.type === "ranking_score") return null;
    const text = (artefact.content as SignalReportArtefactContent | null)
      ?.content;
    return (
      <span className="block text-(--gray-10) text-[13px]">
        {text || "No preview available."}
      </span>
    );
  }
  switch (artefact.type) {
    case "code_reference": {
      const c = artefact.content as CodeReferenceContent;
      return (
        <div>
          <RelevanceNote note={c.relevance_note} />
          <CodeRefBlock
            code={c.contents}
            language={languageFromPath(c.file_path)}
          />
        </div>
      );
    }
    case "line_reference": {
      const c = artefact.content as LineReferenceContent;
      return (
        <div>
          <RelevanceNote note={c.note} />
          {c.contents ? (
            <CodeRefBlock
              code={c.contents}
              language={languageFromPath(c.file_path)}
            />
          ) : null}
        </div>
      );
    }
    case "commit":
      return (
        <ArtefactCommit
          reportId={reportId}
          artefactId={artefact.id}
          content={artefact.content as CommitContent}
          hideDiff={hideCommitDiffs}
        />
      );
    case "task_run":
      return (
        <ArtefactTaskRun content={artefact.content as TaskRunArtefactContent} />
      );
    case "note": {
      const c = artefact.content as NoteContent;
      return <CollapsibleNote note={c.note} author={c.author} />;
    }
    case "priority_judgment": {
      const c = artefact.content as PriorityJudgmentContent;
      return (
        <div className="flex flex-col gap-1">
          <SignalReportPriorityBadge priority={c.priority} />
          {c.explanation ? <CollapsibleReasoning text={c.explanation} /> : null}
        </div>
      );
    }
    case "actionability_judgment": {
      const c = artefact.content as ActionabilityJudgmentContent;
      return (
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <SignalReportActionabilityBadge actionability={c.actionability} />
            {c.already_addressed ? (
              <Badge variant="warning">Already addressed</Badge>
            ) : null}
          </div>
          {c.explanation ? <CollapsibleReasoning text={c.explanation} /> : null}
        </div>
      );
    }
    case "safety_judgment": {
      const c = artefact.content as SafetyJudgmentContent;
      return (
        <div className="flex flex-col gap-1">
          <Badge variant={c.choice ? "success" : "destructive"}>
            {c.choice ? "Safe to act on" : "Unsafe"}
          </Badge>
          {c.explanation ? <CollapsibleReasoning text={c.explanation} /> : null}
        </div>
      );
    }
    case "signal_finding": {
      const c = artefact.content as SignalFindingContent;
      return (
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-(--gray-10) text-[12px]">
              {c.signal_id}
            </span>
            <Badge variant={c.verified ? "success" : "default"}>
              {c.verified ? "Verified" : "Unverified"}
            </Badge>
          </div>
          {c.relevant_code_paths.length > 0 ? (
            <div className="flex flex-col">
              {c.relevant_code_paths.map((path) => (
                <span
                  key={path}
                  className="truncate font-mono text-(--gray-11) text-[12px]"
                >
                  {path}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      );
    }
    case "suggested_reviewers":
      return (
        <ReviewersBody reviewers={artefact.content as SuggestedReviewer[]} />
      );
    case "dismissal": {
      const c = artefact.content as DismissalContent;
      return (
        <div className="flex flex-col gap-1">
          <Badge variant="default">{dismissalReasonLabel(c.reason)}</Badge>
          {c.note ? <RelevanceNote note={c.note} /> : null}
        </div>
      );
    }
    case "ranking_score":
      return (
        <RankingScoreBody content={artefact.content as RankingScoreContent} />
      );
    case "work_claim": {
      const name = (artefact.content as WorkClaimContent).display_name;
      return name ? (
        <span className="block text-(--gray-11) text-[13px]">{name}</span>
      ) : null;
    }
    case "work_release": {
      const c = artefact.content as WorkReleaseContent;
      return (
        <Badge variant="default">{WORK_RELEASE_REASON_LABELS[c.reason]}</Badge>
      );
    }
    default: {
      const c = artefact.content as SignalReportArtefactContent | null;
      const text = typeof c?.content === "string" ? c.content : "";
      return (
        <span className="block text-(--gray-10) text-[13px]">
          {text || "No preview available."}
        </span>
      );
    }
  }
}

function ArtefactRow({
  reportId,
  artefact,
  hideCommitDiffs,
}: {
  reportId: string;
  artefact: AnySignalReportArtefact;
  hideCommitDiffs?: boolean;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const location = locationLabel(artefact);
  const attribution = attributionLabel(artefact);

  return (
    <div className="rounded-lg border border-gray-6 bg-gray-1 p-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="shrink-0 font-medium text-[13px]">
            {typeLabel(artefact)}
          </span>
          {location ? (
            <span className="truncate font-mono text-(--gray-10) text-[12px]">
              {location}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {attribution ? (
            <span className="text-(--gray-10) text-[12px]">
              by {attribution}
            </span>
          ) : null}
          {/* Dev-only escape hatch for inspecting the raw artefact payload. */}
          {import.meta.env.DEV ? (
            <button
              type="button"
              onClick={() => setShowRaw((v) => !v)}
              title="View raw JSON (dev only)"
              aria-pressed={showRaw}
              className={`rounded-sm px-1 font-mono text-[12px] transition-colors hover:bg-(--gray-3) ${
                showRaw ? "text-(--gray-12)" : "text-(--gray-9)"
              }`}
            >
              {"{ }"}
            </button>
          ) : null}
          <RelativeTimestamp timestamp={artefact.created_at} />
        </div>
      </div>
      <ArtefactBody
        reportId={reportId}
        artefact={artefact}
        hideCommitDiffs={hideCommitDiffs}
      />
      {showRaw ? (
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-(--gray-6) bg-(--gray-2) p-2 font-mono text-(--gray-11) text-[12px]">
          {JSON.stringify(artefact, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

export function ArtefactLogList({
  reportId,
  artefacts,
  hideCommitDiffs,
}: {
  reportId: string;
  artefacts: AnySignalReportArtefact[];
  /** Drop the per-commit diff toggle (PR detail shows the full diff already). */
  hideCommitDiffs?: boolean;
}) {
  if (artefacts.length === 0) {
    return null;
  }

  const sorted = [...artefacts].sort(
    (a, b) =>
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );

  return (
    <div className="flex flex-col gap-2">
      {sorted.map((artefact) => (
        <ArtefactRow
          key={artefact.id}
          reportId={reportId}
          artefact={artefact}
          hideCommitDiffs={hideCommitDiffs}
        />
      ))}
    </div>
  );
}
