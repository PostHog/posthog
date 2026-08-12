import { logger } from "../../shell/logger";
import {
  type CspViolationReport,
  cspViolationNotificationSchema,
} from "./schemas";

const log = logger.scope("csp-reporting");

/** Long enough to coalesce the burst a single blocked app produces. */
const FLUSH_DELAY_MS = 500;

/**
 * A frame that violates its policy once usually violates it many times (every
 * blocked image, every retry). Reports repeat, so only distinct ones are worth
 * sending, and only so many of those.
 */
const MAX_DISTINCT_REPORTS = 50;

function dedupeKey(report: CspViolationReport): string {
  const { documentURL, effectiveDirective, blockedURL } = report.body;
  return `${documentURL ?? report.url ?? ""}|${effectiveDirective ?? ""}|${blockedURL ?? ""}`;
}

export interface CspViolationCollectorOptions {
  /** Ships a batch onward; called with at least one report. */
  send: (reports: CspViolationReport[]) => void;
  flushDelayMs?: number;
  maxDistinctReports?: number;
}

/**
 * Collects CSP violations posted out of sandboxed frames (MCP apps, artifact
 * previews) and hands them on in batches.
 *
 * Returns a disposer.
 */
export function startCspViolationCollector({
  send,
  flushDelayMs = FLUSH_DELAY_MS,
  maxDistinctReports = MAX_DISTINCT_REPORTS,
}: CspViolationCollectorOptions): () => void {
  const seen = new Set<string>();
  let pending: CspViolationReport[] = [];
  let flushTimer: ReturnType<typeof setTimeout> | null = null;
  let capReported = false;

  const flush = (): void => {
    flushTimer = null;
    if (pending.length === 0) return;
    const batch = pending;
    pending = [];
    send(batch);
  };

  const onMessage = (event: MessageEvent): void => {
    const parsed = cspViolationNotificationSchema.safeParse(event.data);
    if (!parsed.success) return;

    const report = parsed.data.params.report;
    const key = dedupeKey(report);
    if (seen.has(key)) return;

    if (seen.size >= maxDistinctReports) {
      if (!capReported) {
        capReported = true;
        log.warn(
          `Reached the cap of ${maxDistinctReports} distinct CSP violations; further ones are dropped`,
        );
      }
      return;
    }

    seen.add(key);
    log.warn("CSP violation in sandboxed frame", {
      blockedURL: report.body.blockedURL,
      effectiveDirective: report.body.effectiveDirective,
      disposition: report.body.disposition,
    });

    pending.push(report);
    if (flushTimer === null) {
      flushTimer = setTimeout(flush, flushDelayMs);
    }
  };

  window.addEventListener("message", onMessage);

  return () => {
    window.removeEventListener("message", onMessage);
    if (flushTimer !== null) clearTimeout(flushTimer);
    flush();
  };
}
