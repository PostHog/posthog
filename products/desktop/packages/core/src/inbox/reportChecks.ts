import { formatRelativeTimeLong } from "@posthog/shared";
import type {
  AnySignalReportArtefact,
  CheckResultContent,
  SignalReportCheck,
} from "@posthog/shared/types";
import { prettifyScoutSkillName } from "../scouts/scoutPresentation";

/** Rows past this many collapse the ones that only record how a check ended. */
const ROWS_BEFORE_COLLAPSE = 4;

/** Mirrors `report_check_agent.FALLBACK_CHECK_SKILL_NAME`'s role: the lane a check with no scout runs on. */
const FALLBACK_LANE_LABEL = "The follow-up scout";

/** Mirrors `SignalReportCheck.OPEN_STATUSES`: the two statuses a check can still produce a verdict from. */
const OPEN_STATUSES: SignalReportCheck["status"][] = ["pending", "active"];

/**
 * Colour band for a check's state tag, named for meaning rather than for one host's palette so
 * the desktop rail and the mobile screen can each render it with their own badge.
 */
export type ReportCheckTone =
  | "neutral"
  | "info"
  | "success"
  | "danger"
  | "warning";

export interface ReportCheckRowData {
  check: SignalReportCheck;
  tag: { label: string; tone: ReportCheckTone };
  /** The line under the title: when it runs, who runs it, or what the verdict said. */
  detail: string;
  /** A check a person stopped. The row renders faded with a struck title. */
  cancelled: boolean;
  /** Open checks can still be stopped; terminal ones cannot. */
  cancellable: boolean;
}

/** A soak window in the words the copy needs: "7 days", "36 hours", "90 minutes". */
function soakLabel(minutes: number): string {
  if (minutes % 1440 === 0) {
    const days = minutes / 1440;
    return `${days} ${days === 1 ? "day" : "days"}`;
  }
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return `${hours} ${hours === 1 ? "hour" : "hours"}`;
  }
  return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
}

/** Which scout answers an `agent` check. A `metric_threshold` check has no lane: the coordinator measures it. */
function laneLabel(check: SignalReportCheck): string | null {
  if (check.kind !== "agent") return null;
  const skillName = check.config.skill_name;
  return typeof skillName === "string" && skillName
    ? prettifyScoutSkillName(skillName)
    : FALLBACK_LANE_LABEL;
}

/** "Sep 27", the same short form on both hosts. Future dates read as well as past ones. */
function shortDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** A check is running when its scout run is open; dispatch also pushes `next_run_at` out to the result window. */
function isRunning(check: SignalReportCheck): boolean {
  return check.status === "active" && !!check.dispatched_at;
}

/** A check that ended without a verdict. Nothing is owed on it, so it is the first row to fold away. */
function isRetired(check: SignalReportCheck): boolean {
  return check.status === "expired" || check.status === "cancelled";
}

function joinDetail(parts: (string | null | undefined)[]): string {
  return parts.filter((part): part is string => !!part).join(" · ");
}

function openCheckRow(
  check: SignalReportCheck,
): Pick<ReportCheckRowData, "tag" | "detail"> {
  const lane = laneLabel(check);

  if (check.status === "pending") {
    const start = check.soak_minutes
      ? `Starts ${soakLabel(check.soak_minutes)} after this report is resolved`
      : "Starts when this report is resolved";
    return {
      tag: { label: "Waiting", tone: "neutral" },
      detail: joinDetail([start, lane && `${lane} runs it`]),
    };
  }

  if (isRunning(check)) {
    const startedAgo = formatRelativeTimeLong(check.dispatched_at as string);
    return {
      tag: { label: "Running", tone: "info" },
      detail: lane ? `${lane} started ${startedAgo}` : `Started ${startedAgo}`,
    };
  }

  const work = lane
    ? `${lane} re-probes the claim`
    : "Measures the metric again";
  const runs =
    check.runs_remaining > 1 ? `${check.runs_remaining} runs left` : "1 run";
  const nextRun = shortDate(check.next_run_at);
  return {
    tag: { label: nextRun ? `Runs ${nextRun}` : "Scheduled", tone: "info" },
    detail: joinDetail([
      work,
      runs,
      check.soak_minutes ? `${soakLabel(check.soak_minutes)} soak` : null,
    ]),
  };
}

function terminalCheckRow(
  check: SignalReportCheck,
  explanation: string | undefined,
): Pick<ReportCheckRowData, "tag" | "detail"> {
  const ranOn = shortDate(check.last_run_at);
  const endedOn = shortDate(check.updated_at);

  switch (check.status) {
    case "passed":
      return {
        tag: { label: "Still holds", tone: "success" },
        detail: joinDetail([ranOn, explanation]),
      };
    case "failed":
      return {
        tag: { label: "No longer holds", tone: "danger" },
        detail: joinDetail([ranOn, explanation]),
      };
    case "errored":
      return {
        tag: { label: "Couldn’t measure", tone: "warning" },
        detail: joinDetail([
          `Gave up after ${check.consecutive_errors} tries`,
          ranOn,
          explanation,
        ]),
      };
    case "cancelled":
      return {
        tag: { label: "Cancelled", tone: "neutral" },
        detail: endedOn ? `Stopped ${endedOn}` : "Stopped",
      };
  }

  // Expired: the sweep retired the check when its horizon passed. It may still have run first,
  // because a check that errors its way to its expiry lands here rather than in `errored`.
  return check.last_run_at
    ? {
        tag: { label: "Expired", tone: "neutral" },
        detail: joinDetail([
          `Last ran ${ranOn}`,
          endedOn && `expired ${endedOn}`,
        ]),
      }
    : {
        tag: { label: "Never ran", tone: "neutral" },
        detail: endedOn
          ? `Expired ${endedOn} before it ever ran`
          : "Expired before it ever ran",
      };
}

function timeValue(value: string | null | undefined): number {
  const parsed = value ? new Date(value).getTime() : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * Rank a check for the rail: what is happening now, then what is about to, then what is waiting on
 * the resolve, then the verdicts, and last the checks that ended without one. Scheduled checks sort
 * by their run date and finished ones by how recently they spoke, so the row a reader wants leads
 * each band. Retired rows trail the verdicts because they are also the ones that fold away.
 */
function orderingKey(check: SignalReportCheck): [number, number] {
  if (isRunning(check)) return [0, 0];
  if (check.status === "active") return [1, timeValue(check.next_run_at)];
  if (check.status === "pending") return [2, timeValue(check.next_run_at)];
  if (isRetired(check)) return [4, -timeValue(check.updated_at)];
  return [3, -timeValue(check.last_run_at ?? check.updated_at)];
}

/** The newest `check_result` explanation per check, so a terminal row can say what the verdict found. */
export function latestCheckExplanations(
  artefacts: AnySignalReportArtefact[],
): Map<string, string> {
  const explanations = new Map<string, string>();
  // Artefacts arrive newest first, so the first entry seen for a check is the one that stands.
  for (const artefact of artefacts) {
    if (artefact.type !== "check_result") continue;
    const content = artefact.content as CheckResultContent;
    if (
      content?.check_id &&
      content.explanation?.trim() &&
      !explanations.has(content.check_id)
    ) {
      explanations.set(content.check_id, content.explanation.trim());
    }
  }
  return explanations;
}

export function buildReportCheckRows(
  checks: SignalReportCheck[],
  explanations: Map<string, string>,
): ReportCheckRowData[] {
  return [...checks]
    .sort((a, b) => {
      const [bandA, withinA] = orderingKey(a);
      const [bandB, withinB] = orderingKey(b);
      return bandA - bandB || withinA - withinB;
    })
    .map((check) => {
      const open = OPEN_STATUSES.includes(check.status);
      return {
        check,
        ...(open
          ? openCheckRow(check)
          : terminalCheckRow(check, explanations.get(check.id))),
        cancelled: check.status === "cancelled",
        cancellable: open,
      };
    });
}

/**
 * Split the rows into the ones the section always shows and the ones behind "Show more". Only rows
 * that record how a check ended without a verdict are foldable, so a long history never buries a
 * check that is still running.
 */
export function splitReportCheckRows(rows: ReportCheckRowData[]): {
  visible: ReportCheckRowData[];
  hidden: ReportCheckRowData[];
} {
  const visible: ReportCheckRowData[] = [];
  const hidden: ReportCheckRowData[] = [];
  for (const row of rows) {
    if (isRetired(row.check) && visible.length >= ROWS_BEFORE_COLLAPSE) {
      hidden.push(row);
    } else {
      visible.push(row);
    }
  }
  return { visible, hidden };
}

/** The section header's right-hand summary: how many checks, and then the next thing that happens. */
export function reportChecksMeta(checks: SignalReportCheck[]): string {
  if (checks.some(isRunning)) {
    // A dispatched check's `next_run_at` is the deadline its run has to answer by, so quoting it
    // as the next date would promise a run that is already under way.
    return `${checks.length} · running now`;
  }
  const nextRun = checks
    .filter((check) => check.status === "active")
    .map((check) => check.next_run_at)
    .sort((a, b) => timeValue(a) - timeValue(b))
    .map(shortDate)
    .find((label) => label !== null);
  if (nextRun) {
    return `${checks.length} · next ${nextRun}`;
  }
  if (checks.some((check) => check.status === "pending")) {
    return `${checks.length} · waiting for resolve`;
  }
  return `${checks.length} · all done`;
}
