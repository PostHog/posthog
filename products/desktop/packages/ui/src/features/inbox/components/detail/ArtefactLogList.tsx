import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  CaretRightIcon,
} from "@phosphor-icons/react";
import type {
  ActionabilityJudgmentContent,
  AnySignalReportArtefact,
  CodeReferenceContent,
  CommitContent,
  DismissalContent,
  LineReferenceContent,
  NoteContent,
  PriorityJudgmentContent,
  SafetyJudgmentContent,
  SignalFindingContent,
  SignalReportArtefactContent,
  SuggestedReviewer,
  TaskRunArtefactContent,
} from "@posthog/shared/types";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { ArtefactCommit } from "@posthog/ui/features/inbox/components/detail/ArtefactCommit";
import { ArtefactTaskRun } from "@posthog/ui/features/inbox/components/detail/ArtefactTaskRun";
import { SignalReportActionabilityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportActionabilityBadge";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import { useState } from "react";

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
  dismissal: "Report dismissed",
  video_segment: "Video segment",
};

function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type;
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
function attributionLabel(artefact: AnySignalReportArtefact): string | null {
  if (artefact.created_by) {
    return artefact.created_by.first_name?.trim() || artefact.created_by.email;
  }
  if (artefact.task_id) {
    return "agent";
  }
  return null;
}

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
    <Box className="mt-1.5">
      <CodeBlock size="1">
        <HighlightedCode code={code} language={language} />
      </CodeBlock>
    </Box>
  );
}

function RelevanceNote({ note }: { note: string }) {
  if (!note.trim()) return null;
  return <Text className="block text-(--gray-11) text-[12px]">{note}</Text>;
}

/** Judgment explanations are often paragraphs — collapsed by default behind a toggle. */
function CollapsibleReasoning({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  if (!text.trim()) return null;
  return (
    <Box>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="-mx-1 flex items-center gap-1 rounded-md px-1 py-0.5 text-(--gray-11) text-[12px] transition-colors hover:bg-(--gray-3) hover:text-(--gray-12)"
      >
        {expanded ? (
          <CaretDownIcon size={12} className="shrink-0" />
        ) : (
          <CaretRightIcon size={12} className="shrink-0" />
        )}
        {expanded ? "Hide reasoning" : "Show reasoning"}
      </button>
      {expanded ? (
        <Text className="block text-(--gray-11) text-[12px]">{text}</Text>
      ) : null}
    </Box>
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
    <Box>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="-mx-1 flex w-full items-center gap-1 rounded-md px-1 py-0.5 text-left text-(--gray-11) text-[12px] transition-colors hover:bg-(--gray-3) hover:text-(--gray-12)"
      >
        {expanded ? (
          <CaretDownIcon size={12} className="shrink-0" />
        ) : (
          <CaretRightIcon size={12} className="shrink-0" />
        )}
        {expanded ? (
          "Hide note"
        ) : (
          <Text className="min-w-0 flex-1 truncate">{preview ?? "Note"}</Text>
        )}
      </button>
      {expanded ? (
        <Box className="text-[12px]">
          <MarkdownRenderer content={note} />
          {author ? (
            <Text className="block text-(--gray-10) text-[11px]">
              — {author}
            </Text>
          ) : null}
        </Box>
      ) : null}
    </Box>
  );
}

function ReviewersBody({ reviewers }: { reviewers: SuggestedReviewer[] }) {
  if (reviewers.length === 0) {
    return (
      <Text className="block text-(--gray-10) text-[12px]">
        No reviewers assigned.
      </Text>
    );
  }
  return (
    <Flex direction="column" gap="1">
      {reviewers.map((reviewer) => (
        <Flex
          key={reviewer.user?.uuid ?? reviewer.github_login}
          align="center"
          gap="2"
          wrap="wrap"
        >
          {reviewer.github_login ? (
            <img
              src={`https://github.com/${reviewer.github_login}.png?size=28`}
              alt=""
              className="github-avatar h-[18px] w-[18px] shrink-0 rounded-full"
              onLoad={(e) => e.currentTarget.classList.add("loaded")}
            />
          ) : null}
          <Text className="text-[12px]">
            {reviewer.user?.first_name ??
              reviewer.github_name ??
              reviewer.github_login}
          </Text>
          {reviewer.github_login ? (
            <a
              href={`https://github.com/${reviewer.github_login}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-0.5 text-[11px] text-gray-9 hover:text-gray-11"
            >
              @{reviewer.github_login}
              <ArrowSquareOutIcon size={10} />
            </a>
          ) : null}
        </Flex>
      ))}
    </Flex>
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
    const text = (artefact.content as SignalReportArtefactContent | null)
      ?.content;
    return (
      <Text className="block text-(--gray-10) text-[12px]">
        {text || "No preview available."}
      </Text>
    );
  }
  switch (artefact.type) {
    case "code_reference": {
      const c = artefact.content as CodeReferenceContent;
      return (
        <Box>
          <RelevanceNote note={c.relevance_note} />
          <CodeRefBlock
            code={c.contents}
            language={languageFromPath(c.file_path)}
          />
        </Box>
      );
    }
    case "line_reference": {
      const c = artefact.content as LineReferenceContent;
      return (
        <Box>
          <RelevanceNote note={c.note} />
          {c.contents ? (
            <CodeRefBlock
              code={c.contents}
              language={languageFromPath(c.file_path)}
            />
          ) : null}
        </Box>
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
        <Flex direction="column" gap="1">
          <SignalReportPriorityBadge priority={c.priority} />
          {c.explanation ? <CollapsibleReasoning text={c.explanation} /> : null}
        </Flex>
      );
    }
    case "actionability_judgment": {
      const c = artefact.content as ActionabilityJudgmentContent;
      return (
        <Flex direction="column" gap="1">
          <Flex align="center" gap="2" wrap="wrap">
            <SignalReportActionabilityBadge actionability={c.actionability} />
            {c.already_addressed ? (
              <Badge color="amber" variant="soft">
                Already addressed
              </Badge>
            ) : null}
          </Flex>
          {c.explanation ? <CollapsibleReasoning text={c.explanation} /> : null}
        </Flex>
      );
    }
    case "safety_judgment": {
      const c = artefact.content as SafetyJudgmentContent;
      return (
        <Flex direction="column" gap="1">
          <Badge color={c.choice ? "green" : "red"} variant="soft">
            {c.choice ? "Safe to act on" : "Unsafe"}
          </Badge>
          {c.explanation ? <CollapsibleReasoning text={c.explanation} /> : null}
        </Flex>
      );
    }
    case "signal_finding": {
      const c = artefact.content as SignalFindingContent;
      return (
        <Flex direction="column" gap="1">
          <Flex align="center" gap="2" wrap="wrap">
            <Text className="font-mono text-(--gray-10) text-[11px]">
              {c.signal_id}
            </Text>
            <Badge color={c.verified ? "green" : "gray"} variant="soft">
              {c.verified ? "Verified" : "Unverified"}
            </Badge>
          </Flex>
          {c.relevant_code_paths.length > 0 ? (
            <Flex direction="column">
              {c.relevant_code_paths.map((path) => (
                <Text
                  key={path}
                  className="truncate font-mono text-(--gray-11) text-[11px]"
                >
                  {path}
                </Text>
              ))}
            </Flex>
          ) : null}
        </Flex>
      );
    }
    case "suggested_reviewers":
      return (
        <ReviewersBody reviewers={artefact.content as SuggestedReviewer[]} />
      );
    case "dismissal": {
      const c = artefact.content as DismissalContent;
      return (
        <Flex direction="column" gap="1">
          <Badge color="gray" variant="soft">
            {prettify(c.reason)}
          </Badge>
          {c.note ? <RelevanceNote note={c.note} /> : null}
        </Flex>
      );
    }
    default: {
      const c = artefact.content as SignalReportArtefactContent | null;
      const text = typeof c?.content === "string" ? c.content : "";
      return (
        <Text className="block text-(--gray-10) text-[12px]">
          {text || "No preview available."}
        </Text>
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
    <Box className="rounded-lg border border-gray-6 bg-gray-1 p-3">
      <Flex align="center" justify="between" gap="2" className="mb-1.5">
        <Flex align="center" gap="2" className="min-w-0">
          <Text className="shrink-0 font-medium text-[12px]">
            {typeLabel(artefact.type)}
          </Text>
          {location ? (
            <Text className="truncate font-mono text-(--gray-10) text-[11px]">
              {location}
            </Text>
          ) : null}
        </Flex>
        <Flex align="center" gap="2" className="shrink-0">
          {attribution ? (
            <Text className="text-(--gray-10) text-[11px]">
              by {attribution}
            </Text>
          ) : null}
          {/* Dev-only escape hatch for inspecting the raw artefact payload. */}
          {import.meta.env.DEV ? (
            <button
              type="button"
              onClick={() => setShowRaw((v) => !v)}
              title="View raw JSON (dev only)"
              aria-pressed={showRaw}
              className={`rounded-sm px-1 font-mono text-[11px] transition-colors hover:bg-(--gray-3) ${
                showRaw ? "text-(--gray-12)" : "text-(--gray-9)"
              }`}
            >
              {"{ }"}
            </button>
          ) : null}
          <RelativeTimestamp timestamp={artefact.created_at} />
        </Flex>
      </Flex>
      <ArtefactBody
        reportId={reportId}
        artefact={artefact}
        hideCommitDiffs={hideCommitDiffs}
      />
      {showRaw ? (
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-(--gray-6) bg-(--gray-2) p-2 font-mono text-(--gray-11) text-[11px]">
          {JSON.stringify(artefact, null, 2)}
        </pre>
      ) : null}
    </Box>
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
    <Flex direction="column" gap="2">
      {sorted.map((artefact) => (
        <ArtefactRow
          key={artefact.id}
          reportId={reportId}
          artefact={artefact}
          hideCommitDiffs={hideCommitDiffs}
        />
      ))}
    </Flex>
  );
}
