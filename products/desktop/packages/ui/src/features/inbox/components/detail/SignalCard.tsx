import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  CaretRightIcon,
  CheckCircleIcon,
  TagIcon,
} from "@phosphor-icons/react";
import type { Signal, SignalFindingContent } from "@posthog/shared/types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { errorTrackingIssueUrl } from "@posthog/ui/utils/posthogLinks";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  type SignalInteractionAction,
  SignalInteractionContext,
  useSignalInteraction,
} from "./signalInteractionContext";

const COLLAPSE_THRESHOLD = 300;

// ── Source line labels (matching PostHog Cloud's signalCardSourceLine) ────────

const ERROR_TRACKING_TYPE_LABELS: Record<string, string> = {
  issue_created: "New issue",
  issue_reopened: "Issue reopened",
  issue_spiking: "Volume spike",
};

// Turn a scout's skill_name (e.g. "signals-scout-error-tracking") into a
// human-friendly label (e.g. "Error tracking").
function prettifyScoutName(skillName: string): string {
  const cleaned = skillName
    .replace(/^signals-scout-/, "")
    .replace(/[-_]/g, " ")
    .trim();
  if (!cleaned) return "";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function signalCardSourceLine(signal: {
  source_product: string;
  source_type: string;
  extra?: Record<string, unknown>;
}): string {
  const { source_product, source_type } = signal;

  if (source_product === "error_tracking") {
    const typeLabel =
      ERROR_TRACKING_TYPE_LABELS[source_type] ?? source_type.replace(/_/g, " ");
    return `Error tracking · ${typeLabel}`;
  }
  if (
    source_product === "session_replay" &&
    source_type === "session_problem"
  ) {
    return "Session replay · Session problem";
  }
  if (
    source_product === "session_replay" &&
    source_type === "session_segment_cluster"
  ) {
    return "Session replay · Session segment cluster";
  }
  if (
    source_product === "session_replay" &&
    source_type === "session_analysis_cluster"
  ) {
    return "Session replay · Session analysis cluster";
  }
  if (source_product === "llm_analytics" && source_type === "evaluation") {
    return "AI observability · Evaluation";
  }
  if (source_product === "zendesk" && source_type === "ticket") {
    return "Zendesk · Ticket";
  }
  if (source_product === "github" && source_type === "issue") {
    return "GitHub · Issue";
  }
  if (source_product === "linear" && source_type === "issue") {
    return "Linear · Issue";
  }
  if (source_product === "pganalyze" && source_type === "issue") {
    return "pganalyze · Issue";
  }
  if (source_product === "health_checks" && source_type === "health_issue") {
    return "Health checks · Issue";
  }
  if (
    source_product === "signals_scout" &&
    source_type === "cross_source_issue"
  ) {
    const skillName =
      typeof signal.extra?.skill_name === "string"
        ? prettifyScoutName(signal.extra.skill_name)
        : "";
    return skillName ? `Scout · ${skillName}` : "Scout · Cross-source issue";
  }

  const productLabel = source_product.replace(/_/g, " ");
  const typeLabel = source_type.replace(/_/g, " ");
  return `${productLabel} · ${typeLabel}`;
}

// ── Shared utilities ─────────────────────────────────────────────────────────

interface GitHubLabelObject {
  name: string;
  color?: string;
}

interface GitHubIssueExtra {
  html_url?: string;
  number?: number;
  labels?: string | GitHubLabelObject[];
  created_at?: string;
}

interface ZendeskTicketExtra {
  url?: string;
  priority?: string;
  status?: string;
  tags?: string[];
}

interface LlmEvalExtra {
  evaluation_id?: string;
  trace_id?: string;
  model?: string;
  provider?: string;
}

interface SessionProblemExtra {
  session_id?: string;
  segment_title?: string;
  start_time?: string;
  end_time?: string;
  problem_type?: string;
  distinct_id?: string;
  session_start_time?: string;
  session_end_time?: string;
  session_duration?: number;
  session_active_seconds?: number;
  exported_asset_id?: number;
}

interface ErrorTrackingExtra {
  fingerprint?: string;
}

function resolveLabels(
  raw: GitHubIssueExtra["labels"],
): { name: string; color?: string }[] {
  if (!raw) return [];
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed.map((l: string | GitHubLabelObject) =>
          typeof l === "string"
            ? { name: l }
            : { name: l.name, color: l.color },
        );
      }
    } catch {
      return [];
    }
  }
  if (Array.isArray(raw)) {
    return raw.map((l) =>
      typeof l === "string" ? { name: l } : { name: l.name, color: l.color },
    );
  }
  return [];
}

function truncateBody(body: string, maxLength = COLLAPSE_THRESHOLD): string {
  if (body.length <= maxLength) return body;
  const truncated = body.slice(0, maxLength);
  const lastNewline = truncated.lastIndexOf("\n");
  const cutPoint = lastNewline > maxLength * 0.5 ? lastNewline : maxLength;
  let result = truncated.slice(0, cutPoint);
  // Close any open code fences so markdown renders cleanly
  const fenceCount = (result.match(/^```/gm) || []).length;
  if (fenceCount % 2 !== 0) {
    // Trim trailing partial fence line (e.g. just "```" with no content after)
    const lastFence = result.lastIndexOf("```");
    const afterFence = result.slice(lastFence + 3).trim();
    if (!afterFence) {
      result = result.slice(0, lastFence).trimEnd();
    } else {
      result += "\n```";
    }
  }
  return `${result}\n\n…`;
}

function zendeskWebUrl(apiUrl: string): string {
  const match = apiUrl.match(
    /^(https?:\/\/[^/]+)\/api\/v2\/tickets\/(\d+)(?:\.json)?(?:[?#].*)?$/,
  );
  if (!match) return apiUrl;
  const [, origin, id] = match;
  return `${origin}/agent/tickets/${id}`;
}

function parseExtra(raw: Record<string, unknown>): Record<string, unknown> {
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  return raw;
}

// ── Type guards ──────────────────────────────────────────────────────────────

function isGithubIssueExtra(
  extra: Record<string, unknown>,
): extra is Record<string, unknown> & GitHubIssueExtra {
  return "html_url" in extra && "number" in extra;
}

function isZendeskTicketExtra(
  extra: Record<string, unknown>,
): extra is Record<string, unknown> & ZendeskTicketExtra {
  return "url" in extra && "priority" in extra;
}

function isLlmEvalExtra(
  extra: Record<string, unknown>,
): extra is Record<string, unknown> & LlmEvalExtra {
  return "evaluation_id" in extra && "trace_id" in extra;
}

function isSessionProblemExtra(
  extra: Record<string, unknown>,
): extra is Record<string, unknown> & SessionProblemExtra {
  return (
    "session_id" in extra && "problem_type" in extra && "segment_title" in extra
  );
}

function isErrorTrackingExtra(
  extra: Record<string, unknown>,
): extra is Record<string, unknown> & ErrorTrackingExtra {
  return typeof extra.fingerprint === "string";
}

// ── Shared components ────────────────────────────────────────────────────────

function VerificationBadge() {
  return (
    <Flex
      align="center"
      gap="1"
      className="shrink-0 text-(--green-9) text-[11px]"
      title="Verified by code or data evidence"
    >
      <CheckCircleIcon size={12} weight="fill" />
      <span>Verified</span>
    </Flex>
  );
}

function SignalCardHeader({
  signal,
  verified,
}: {
  signal: Signal;
  verified?: boolean;
}) {
  const meta = getSourceProductMeta(signal.source_product);

  return (
    <Flex align="center" gap="2" className="mb-2 cursor-default select-none">
      <span
        className="shrink-0"
        style={{ color: meta?.color ?? "var(--gray-9)" }}
      >
        {meta ? (
          <meta.Icon size={14} />
        ) : (
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-(--gray-9)" />
        )}
      </span>
      <Text className="font-medium text-[13px] text-gray-10">
        {signalCardSourceLine({ ...signal, extra: parseExtra(signal.extra) })}
      </Text>
      <span className="flex-1" />
      <RelativeTimestamp timestamp={signal.timestamp} />
      {verified === true && <VerificationBadge />}
    </Flex>
  );
}

function CollapsibleBody({ body }: { body: string }) {
  const [expanded, setExpanded] = useState(false);
  const interaction = useSignalInteraction();
  const isLong = body.length > COLLAPSE_THRESHOLD;
  // Preprocess content to handle escaped backticks and ensure proper markdown parsing
  const processedBody = body
    .replace(/\\`/g, "`") // Unescape escaped backticks
    .replace(/`([^`]+)`/g, "`$1`"); // Ensure proper backtick formatting
  const displayBody =
    isLong && !expanded ? truncateBody(processedBody) : processedBody;

  return (
    <Box>
      <Box className="text-pretty break-words text-[13px] text-gray-11 leading-relaxed [&_code]:text-[11px] [&_p:last-child]:mb-0 [&_p]:mb-1 [&_pre]:text-[11px]">
        <MarkdownRenderer content={displayBody} />
      </Box>
      {isLong && (
        <button
          type="button"
          onClick={() => {
            setExpanded((v) => {
              const next = !v;
              interaction?.onInteraction({
                type: next ? "expand_signal" : "collapse_signal",
              });
              return next;
            });
          }}
          className="mt-1.5 flex items-center gap-1 rounded px-1 py-0.5 font-medium text-[12px] text-accent-11 hover:bg-accent-3 hover:text-accent-12"
        >
          {expanded ? (
            <CaretDownIcon size={12} />
          ) : (
            <CaretRightIcon size={12} />
          )}
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </Box>
  );
}

// ── Source-specific cards ────────────────────────────────────────────────────

function GitHubIssueSignalCard({
  signal,
  extra,
  verified,
  codePaths,
  dataQueried,
}: {
  signal: Signal;
  extra: GitHubIssueExtra;
  verified?: boolean;
  codePaths?: string[];
  dataQueried?: string;
}) {
  const labels = resolveLabels(extra.labels);
  const issueUrl = extra.html_url ?? null;

  return (
    <Box className="min-w-0 overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1 p-3">
      <SignalCardHeader signal={signal} verified={verified} />
      <CollapsibleBody body={signal.content} />
      <Flex
        align="center"
        gap="2"
        wrap="wrap"
        mt="2"
        className="text-[11px] text-gray-10"
      >
        <Text className="font-medium text-[11px]">#{extra.number}</Text>
        {labels.map((label) => (
          <span
            key={label.name}
            className="inline-flex items-center rounded-full px-1.5 py-0.5 font-medium text-[11px]"
            style={
              label.color
                ? {
                    backgroundColor: `#${label.color}20`,
                    color: `#${label.color}`,
                    border: `1px solid #${label.color}40`,
                  }
                : {
                    backgroundColor: "var(--gray-3)",
                    color: "var(--gray-11)",
                    border: "1px solid var(--gray-6)",
                  }
            }
          >
            <TagIcon size={10} className="mr-0.5" />
            {label.name}
          </span>
        ))}
        <span className="flex-1" />
        {issueUrl && (
          <a
            href={issueUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-gray-10 hover:text-gray-12"
          >
            View on GitHub
            <ArrowSquareOutIcon size={12} />
          </a>
        )}
      </Flex>
      {extra.created_at && (
        <Text className="mt-1 block text-[11px] text-gray-10">
          Opened: {new Date(extra.created_at).toLocaleString()}
        </Text>
      )}
      <CodePathsCollapsible paths={codePaths ?? []} />
      <DataQueriedCollapsible text={dataQueried ?? ""} />
    </Box>
  );
}

function ZendeskTicketSignalCard({
  signal,
  extra,
  verified,
  codePaths,
  dataQueried,
}: {
  signal: Signal;
  extra: ZendeskTicketExtra;
  verified?: boolean;
  codePaths?: string[];
  dataQueried?: string;
}) {
  return (
    <Box className="min-w-0 overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1 p-3">
      <SignalCardHeader signal={signal} verified={verified} />
      <CollapsibleBody body={signal.content} />
      <Flex
        align="center"
        gap="2"
        wrap="wrap"
        mt="2"
        className="text-[11px] text-gray-10"
      >
        {extra.priority && (
          <Badge variant="soft" color="gray" size="1" className="text-[11px]">
            Priority: {extra.priority}
          </Badge>
        )}
        {extra.status && (
          <Badge variant="soft" color="gray" size="1" className="text-[11px]">
            Status: {extra.status}
          </Badge>
        )}
        {extra.tags?.map((tag) => (
          <Badge
            key={tag}
            variant="soft"
            color="gray"
            size="1"
            className="text-[11px]"
          >
            {tag}
          </Badge>
        ))}
        <span className="flex-1" />
        {extra.url && (
          <a
            href={zendeskWebUrl(extra.url)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-gray-10 hover:text-gray-12"
          >
            Open
            <ArrowSquareOutIcon size={12} />
          </a>
        )}
      </Flex>
      <CodePathsCollapsible paths={codePaths ?? []} />
      <DataQueriedCollapsible text={dataQueried ?? ""} />
    </Box>
  );
}

function LlmEvalSignalCard({
  signal,
  extra,
  verified,
  codePaths,
  dataQueried,
}: {
  signal: Signal;
  extra: LlmEvalExtra;
  verified?: boolean;
  codePaths?: string[];
  dataQueried?: string;
}) {
  return (
    <Box className="min-w-0 overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1 p-3">
      <SignalCardHeader signal={signal} verified={verified} />
      <CollapsibleBody body={signal.content} />
      <Flex align="center" gap="2" mt="2" className="text-[11px] text-gray-10">
        {extra.model && <span>Model: {extra.model}</span>}
        {extra.model && extra.provider && <span>·</span>}
        {extra.provider && <span>Provider: {extra.provider}</span>}
      </Flex>
      {extra.trace_id && (
        <Text className="mt-1 block text-[11px] text-gray-10">
          Trace:{" "}
          <span className="font-mono">{extra.trace_id.slice(0, 12)}...</span>
        </Text>
      )}
      <CodePathsCollapsible paths={codePaths ?? []} />
      <DataQueriedCollapsible text={dataQueried ?? ""} />
    </Box>
  );
}

const PROBLEM_TYPE_LABELS: Record<
  string,
  { label: string; color: "red" | "orange" }
> = {
  blocking_exception: { label: "Blocking exception", color: "red" },
  non_blocking_exception: { label: "Non-blocking exception", color: "orange" },
  abandonment: { label: "Abandonment", color: "red" },
  confusion: { label: "Confusion", color: "orange" },
  failure: { label: "Failure", color: "red" },
};

function formatSessionDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins < 60) return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const remainMins = mins % 60;
  return remainMins > 0 ? `${hrs}h ${remainMins}m` : `${hrs}h`;
}

function SessionProblemSignalCard({
  signal,
  extra,
  verified,
  codePaths,
  dataQueried,
}: {
  signal: Signal;
  extra: SessionProblemExtra;
  verified?: boolean;
  codePaths?: string[];
  dataQueried?: string;
}) {
  const problemInfo = extra.problem_type
    ? (PROBLEM_TYPE_LABELS[extra.problem_type] ?? {
        label: extra.problem_type.replace(/_/g, " "),
        color: "orange" as const,
      })
    : null;

  return (
    <Box className="min-w-0 overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1 p-3">
      <SignalCardHeader signal={signal} verified={verified} />
      {extra.segment_title && (
        <Text mt="1" className="font-medium text-[13px] text-gray-11" as="p">
          {extra.segment_title}
        </Text>
      )}
      <CollapsibleBody body={signal.content} />

      {extra.session_id && (
        <SessionRecordingVideo
          exportedAssetId={extra.exported_asset_id}
          sessionId={extra.session_id}
        />
      )}

      <Flex
        align="center"
        gap="2"
        wrap="wrap"
        mt="2"
        className="text-[11px] text-gray-10"
      >
        {problemInfo && (
          <Badge
            variant="soft"
            color={problemInfo.color}
            size="1"
            className="text-[11px]"
          >
            {problemInfo.label}
          </Badge>
        )}
        {extra.distinct_id && (
          <Text className="font-mono text-[11px]">
            {extra.distinct_id.slice(0, 10)}…
          </Text>
        )}
        {extra.start_time && extra.end_time && (
          <>
            <span>·</span>
            <span>
              {extra.start_time} – {extra.end_time}
            </span>
          </>
        )}
        {extra.session_duration != null && (
          <>
            <span>·</span>
            <span>{formatSessionDuration(extra.session_duration)} session</span>
          </>
        )}
        {extra.session_active_seconds != null &&
          extra.session_duration != null &&
          extra.session_duration > 0 && (
            <>
              <span>·</span>
              <span>
                {Math.round(
                  (extra.session_active_seconds / extra.session_duration) * 100,
                )}
                % active
              </span>
            </>
          )}
      </Flex>
      <CodePathsCollapsible paths={codePaths ?? []} />
      <DataQueriedCollapsible text={dataQueried ?? ""} />
    </Box>
  );
}

function SessionRecordingVideo({
  exportedAssetId,
  sessionId,
}: {
  exportedAssetId?: number;
  sessionId: string;
}) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const videoRef = useRef<HTMLVideoElement>(null);
  const hasFiredPlayRef = useRef(false);
  const interaction = useSignalInteraction();
  const videoQuery = useAuthenticatedQuery<string | null>(
    ["export-video", projectId, exportedAssetId, sessionId],
    async (client) => {
      if (!projectId) return null;
      let assetId: number | null = exportedAssetId ?? null;
      // If no asset ID in the signal, look up the export by session_id
      if (assetId == null) {
        assetId = await client.findExportBySessionRecordingId(
          projectId,
          sessionId,
        );
        if (assetId == null) return null;
      }
      return client.getExportContentUrl(projectId, assetId);
    },
    { enabled: !!projectId, staleTime: Infinity },
  );

  if (videoQuery.isError || videoQuery.data === null) return null;
  if (videoQuery.isLoading || videoQuery.data === undefined) {
    return (
      <Box
        mt="2"
        className="flex h-24 items-center justify-center rounded bg-gray-3 text-[11px] text-gray-9"
      >
        Loading recording…
      </Box>
    );
  }

  return (
    <Box mt="2" className="overflow-hidden rounded">
      <video
        ref={videoRef}
        src={videoQuery.data}
        controls
        muted
        preload="metadata"
        className="max-h-[300px] w-full rounded"
        onPlay={() => {
          if (hasFiredPlayRef.current) return;
          hasFiredPlayRef.current = true;
          interaction?.onInteraction({ type: "play_session_recording" });
        }}
      />
    </Box>
  );
}

function ErrorTrackingSignalCard({
  signal,
  extra,
  verified,
  codePaths,
  dataQueried,
}: {
  signal: Signal;
  extra: ErrorTrackingExtra;
  verified?: boolean;
  codePaths?: string[];
  dataQueried?: string;
}) {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const issueUrl = signal.source_id
    ? errorTrackingIssueUrl(signal.source_id, {
        projectId,
        cloudRegion,
        fingerprint: extra.fingerprint,
      })
    : null;

  return (
    <Box className="min-w-0 overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1 p-3">
      <SignalCardHeader signal={signal} verified={verified} />
      <CollapsibleBody body={signal.content} />
      {issueUrl && (
        <Flex
          align="center"
          justify="end"
          mt="2"
          className="text-[11px] text-gray-10"
        >
          <a
            href={issueUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-gray-10 hover:text-gray-12"
          >
            View issue
            <ArrowSquareOutIcon size={12} />
          </a>
        </Flex>
      )}
      <CodePathsCollapsible paths={codePaths ?? []} />
      <DataQueriedCollapsible text={dataQueried ?? ""} />
    </Box>
  );
}

function GenericSignalCard({
  signal,
  verified,
  codePaths,
  dataQueried,
}: {
  signal: Signal;
  verified?: boolean;
  codePaths?: string[];
  dataQueried?: string;
}) {
  return (
    <Box className="min-w-0 overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1 p-3">
      <SignalCardHeader signal={signal} verified={verified} />
      <CollapsibleBody body={signal.content} />
      <CodePathsCollapsible paths={codePaths ?? []} />
      <DataQueriedCollapsible text={dataQueried ?? ""} />
    </Box>
  );
}

function CodePathsCollapsible({ paths }: { paths: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const interaction = useSignalInteraction();

  if (paths.length === 0) return null;

  return (
    <Box mt="2" pt="2" className="border-t border-t-(--gray-5)">
      <button
        type="button"
        onClick={() => {
          setExpanded((v) => {
            const next = !v;
            if (next) {
              interaction?.onInteraction({
                type: "expand_signal_section",
                section: "relevant_code",
              });
            }
            return next;
          });
        }}
        className="flex items-center gap-1 rounded px-1 py-0.5 font-medium text-[12px] text-gray-10 hover:bg-gray-3 hover:text-gray-12"
      >
        {expanded ? <CaretDownIcon size={12} /> : <CaretRightIcon size={12} />}
        Relevant code ({paths.length})
      </button>
      {expanded && (
        <Flex direction="column" gap="1" mt="1" className="pl-[18px]">
          {paths.map((raw) => {
            const trimmed = raw.trim();
            const parenIdx = trimmed.indexOf(" (");
            const filePath =
              parenIdx >= 0 ? trimmed.slice(0, parenIdx) : trimmed;
            const comment = parenIdx >= 0 ? trimmed.slice(parenIdx + 1) : null;
            return (
              <Text key={raw} className="text-[11px]">
                <span className="font-mono text-gray-12">{filePath}</span>
                {comment && (
                  <span className="ml-1 text-(--gray-9)">{comment}</span>
                )}
              </Text>
            );
          })}
        </Flex>
      )}
    </Box>
  );
}

function DataQueriedCollapsible({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const interaction = useSignalInteraction();

  if (!text.trim()) return null;

  return (
    <Box mt="2" pt="2" className="border-t border-t-(--gray-5)">
      <button
        type="button"
        onClick={() => {
          setExpanded((v) => {
            const next = !v;
            if (next) {
              interaction?.onInteraction({
                type: "expand_signal_section",
                section: "data_queried",
              });
            }
            return next;
          });
        }}
        className="flex items-center gap-1 rounded px-1 py-0.5 font-medium text-[12px] text-gray-10 hover:bg-gray-3 hover:text-gray-12"
      >
        {expanded ? <CaretDownIcon size={12} /> : <CaretRightIcon size={12} />}
        Data queried
      </button>
      {expanded && (
        <Text
          color="gray"
          className="mt-1 block whitespace-pre-wrap text-pretty pl-[18px] text-[11px] leading-relaxed"
        >
          {text}
        </Text>
      )}
    </Box>
  );
}

// ── Main export ──────────────────────────────────────────────────────────────

export function SignalCard({
  signal,
  finding,
  onInteraction,
}: {
  signal: Signal;
  finding?: SignalFindingContent;
  onInteraction?: (action: SignalInteractionAction) => void;
}) {
  const extra = parseExtra(signal.extra);
  const verified = finding?.verified;
  const codePaths = finding?.relevant_code_paths ?? [];
  const dataQueried = finding?.data_queried ?? "";

  const handleInteraction = useCallback(
    (action: SignalInteractionAction) => {
      onInteraction?.(action);
    },
    [onInteraction],
  );

  const ctxValue = useMemo(
    () => ({ signal, onInteraction: handleInteraction }),
    [signal, handleInteraction],
  );

  // Delegated click handler: detect external-link clicks anywhere inside the card.
  const handleCardClickCapture = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      const anchor = target.closest("a");
      if (!anchor) return;
      if (anchor.getAttribute("target") !== "_blank") return;
      handleInteraction({ type: "view_signal_external" });
    },
    [handleInteraction],
  );

  let content: React.ReactNode;
  if (
    signal.source_product === "session_replay" &&
    signal.source_type === "session_problem" &&
    isSessionProblemExtra(extra)
  ) {
    content = (
      <SessionProblemSignalCard
        signal={signal}
        extra={extra}
        verified={verified}
        codePaths={codePaths}
        dataQueried={dataQueried}
      />
    );
  } else if (
    signal.source_product === "error_tracking" &&
    isErrorTrackingExtra(extra)
  ) {
    content = (
      <ErrorTrackingSignalCard
        signal={signal}
        extra={extra}
        verified={verified}
        codePaths={codePaths}
        dataQueried={dataQueried}
      />
    );
  } else if (signal.source_product === "github" && isGithubIssueExtra(extra)) {
    content = (
      <GitHubIssueSignalCard
        signal={signal}
        extra={extra}
        verified={verified}
        codePaths={codePaths}
        dataQueried={dataQueried}
      />
    );
  } else if (
    signal.source_product === "zendesk" &&
    isZendeskTicketExtra(extra)
  ) {
    content = (
      <ZendeskTicketSignalCard
        signal={signal}
        extra={extra}
        verified={verified}
        codePaths={codePaths}
        dataQueried={dataQueried}
      />
    );
  } else if (
    signal.source_product === "llm_analytics" &&
    isLlmEvalExtra(extra)
  ) {
    content = (
      <LlmEvalSignalCard
        signal={signal}
        extra={extra}
        verified={verified}
        codePaths={codePaths}
        dataQueried={dataQueried}
      />
    );
  } else {
    content = (
      <GenericSignalCard
        signal={signal}
        verified={verified}
        codePaths={codePaths}
      />
    );
  }

  return (
    <SignalInteractionContext.Provider value={ctxValue}>
      <div onClickCapture={handleCardClickCapture}>{content}</div>
    </SignalInteractionContext.Provider>
  );
}
