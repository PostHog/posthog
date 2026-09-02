import type { DocSchemas } from "@posthog/api-client/docs";
import { cn } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { DocMark, type DocMarkState } from "@posthog/ui/primitives/DocMark";
import { toast } from "@posthog/ui/primitives/toast";
import { useDiscussionMutations } from "../hooks/useDocDiscussions";
import { plainLine } from "./DocThreadRow";
import {
  SPACE_ROW_ACTION_CLASS,
  SpaceRow,
  SpaceSectionHeader,
} from "./SpaceRow";

const VERDICT_LABEL: Record<DocSchemas.WatchVerdictState, string> = {
  pending: "Compiling",
  holding: "Holding",
  moved: "Moved",
  confirmed: "Confirmed",
  refuted: "Refuted",
  stale: "Could not check",
};

/** The verdicts that ask a person to look. */
const ATTENTION_TONE: Partial<Record<DocSchemas.WatchVerdictState, string>> = {
  moved: "text-(--amber-11)",
  refuted: "text-(--red-11)",
};

function needsAttention(watch: DocSchemas.WatchSummary): boolean {
  return (
    watch.status === "active" &&
    (watch.verdict === "moved" || watch.verdict === "refuted")
  );
}

function stateLabel(watch: DocSchemas.WatchSummary): string | null {
  if (watch.status === "paused") return "Paused";
  if (watch.status === "stopped") {
    return watch.verdict === "confirmed" || watch.verdict === "refuted"
      ? VERDICT_LABEL[watch.verdict]
      : "Stopped";
  }
  // A watch that is still compiling has nothing to say yet.
  if (watch.verdict === "pending") return null;
  return VERDICT_LABEL[watch.verdict];
}

function markState(watch: DocSchemas.WatchSummary): DocMarkState {
  if (watch.status !== "active") return "handled";
  if (watch.verdict === "moved") return "moved";
  if (watch.verdict === "stale") return "stale";
  return "still";
}

function byAttentionThenRecency(
  a: DocSchemas.WatchSummary,
  b: DocSchemas.WatchSummary,
): number {
  const attention = Number(needsAttention(b)) - Number(needsAttention(a));
  if (attention !== 0) return attention;
  const active = Number(b.status === "active") - Number(a.status === "active");
  if (active !== 0) return active;
  return (b.last_report_at ?? "").localeCompare(a.last_report_at ?? "");
}

function WatchRow({
  channelId,
  watch,
}: {
  channelId: string;
  watch: DocSchemas.WatchSummary;
}) {
  const mutation = useDiscussionMutations(watch.doc_id).watch;
  const active = watch.status === "active";
  const decided = watch.verdict === "confirmed" || watch.verdict === "refuted";
  const label = stateLabel(watch);
  const report = watch.last_report ? plainLine(watch.last_report) : null;
  const excerpt =
    label || report ? (
      <>
        {label ? (
          <span className={cn("font-medium", ATTENTION_TONE[watch.verdict])}>
            {label}
          </span>
        ) : null}
        {label && report ? " · " : null}
        {report}
      </>
    ) : null;

  return (
    <SpaceRow
      icon={<DocMark variant="agent" state={markState(watch)} size={11} />}
      title={`“${watch.anchor_text || "a section"}”`}
      meta={watch.doc_title || "Untitled"}
      age={
        watch.last_report_at
          ? formatRelativeTimeShort(watch.last_report_at)
          : undefined
      }
      excerpt={excerpt}
      muted={!active}
      link={{
        to: "/spaces/$channelId/docs/$docId",
        params: { channelId, docId: watch.doc_id },
        search: { thread: watch.anchor_key },
      }}
      action={
        decided ? null : (
          <button
            type="button"
            className={SPACE_ROW_ACTION_CLASS}
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate(
                {
                  threadId: watch.thread_id,
                  body: { action: active ? "stop" : "resume" },
                },
                {
                  onError: () => toast.error("The watch did not take that"),
                },
              )
            }
          >
            {active ? "Stop" : "Resume"}
          </button>
        )
      }
    />
  );
}

/**
 * The claims the space keeps watching, across its pages. The ones that need a
 * person come first, then the active ones by their latest report, then the
 * paused and stopped ones.
 */
export function SpaceWatchList({
  channelId,
  watches,
}: {
  channelId: string;
  watches: DocSchemas.WatchSummary[];
}) {
  if (watches.length === 0) return null;
  const sorted = [...watches].sort(byAttentionThenRecency);
  const moved = watches.filter(needsAttention).length;
  const active = watches.filter((watch) => watch.status === "active").length;
  return (
    <section className="shrink-0">
      <SpaceSectionHeader
        title="Watching"
        aside={
          <span
            className={cn(
              "text-[12.5px] tabular-nums",
              moved ? "text-(--amber-11)" : "text-(--gray-9)",
            )}
          >
            {moved ? `${moved} moved` : `${active} active`}
          </span>
        }
      />
      <ul className="-mx-2 pt-1.5">
        {sorted.map((watch) => (
          <WatchRow key={watch.thread_id} channelId={channelId} watch={watch} />
        ))}
      </ul>
    </section>
  );
}
