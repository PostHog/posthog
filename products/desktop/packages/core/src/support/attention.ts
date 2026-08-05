import type { Ticket } from "@posthog/api-client/posthog-client";

/**
 * The attention queue's pure core: classify each ticket into a reason-tagged
 * actionability state, then rank deterministically. No I/O, no LLM, no
 * Date.now() — callers pass `now`, so identical inputs always produce the
 * identical order (see docs/plans/future-support.md, PR 2).
 */

export type AttentionState =
  /** SLA deadline has passed. */
  | "sla-breached"
  /** Ticket was waiting on the customer and they wrote back — the resume signal. */
  | "customer-replied"
  /**
   * A linked agent task finished and needs human review. Never produced yet:
   * the ticket↔task link (Task.ticket) ships with the server-side checklist
   * PR (4a). Ranking already handles it so the join slots in without a
   * reorder of everything below.
   */
  | "agent-handed-back"
  /** SLA due within SLA_AT_RISK_WINDOW_MS. */
  | "sla-at-risk"
  /** Snooze expired without customer activity. */
  | "snooze-elapsed"
  /** New and never prioritised — unknown urgency, not low urgency. */
  | "untriaged"
  /** Being worked; nothing new since last touch. */
  | "in-progress"
  /** Ball is in the customer's court. */
  | "waiting-on-customer"
  /** Deliberately parked until snoozed_until. */
  | "snoozed";

export interface ClassifiedTicket {
  ticket: Ticket;
  state: AttentionState;
}

/** How close an SLA deadline must be to count as at-risk. A tuning knob, not
 * a design constant — see the plan's open questions. */
export const SLA_AT_RISK_WINDOW_MS = 2 * 60 * 60 * 1000;

/** Lower tier = higher in the queue. */
const STATE_TIER: Record<AttentionState, number> = {
  "sla-breached": 0,
  "customer-replied": 1,
  "agent-handed-back": 2,
  "sla-at-risk": 3,
  "snooze-elapsed": 4,
  untriaged: 5,
  "in-progress": 6,
  "waiting-on-customer": 7,
  snoozed: 8,
};

/**
 * Priority weight for ordering within a tier. Null priority is untriaged —
 * unknown urgency deliberately outranks known-low so triage debt can't hide
 * at the bottom of the queue.
 */
function priorityWeight(priority: Ticket["priority"]): number {
  switch (priority) {
    case "high":
      return 3;
    case "medium":
      return 2;
    case "low":
      return 1;
    default:
      return 1.5;
  }
}

export function classifyAttention(ticket: Ticket, now: Date): AttentionState {
  const status = ticket.status ?? "new";
  const nowMs = now.getTime();

  const slaDueMs = parseTime(ticket.sla_due_at);
  if (slaDueMs !== null && slaDueMs < nowMs) return "sla-breached";

  const waitingOnCustomer = status === "pending" || status === "on_hold";
  if (waitingOnCustomer && ticket.unread_team_count > 0) {
    return "customer-replied";
  }

  if (slaDueMs !== null && slaDueMs - nowMs <= SLA_AT_RISK_WINDOW_MS) {
    return "sla-at-risk";
  }

  const snoozedUntilMs = parseTime(ticket.snoozed_until);
  if (snoozedUntilMs !== null) {
    return snoozedUntilMs <= nowMs ? "snooze-elapsed" : "snoozed";
  }

  if (waitingOnCustomer) return "waiting-on-customer";

  if (status === "new" && !hasPriority(ticket.priority)) return "untriaged";

  return "in-progress";
}

/**
 * Classify and order the queue. Resolved tickets are excluded — they need no
 * attention. Deterministic for a fixed `now`: tier, then priority (unknown
 * between medium and low), then latest activity, then ticket number.
 */
export function rankQueue(tickets: Ticket[], now: Date): ClassifiedTicket[] {
  return tickets
    .filter((ticket) => ticket.status !== "resolved")
    .map((ticket) => ({ ticket, state: classifyAttention(ticket, now) }))
    .sort((a, b) => {
      const tier = STATE_TIER[a.state] - STATE_TIER[b.state];
      if (tier !== 0) return tier;
      const weight =
        priorityWeight(b.ticket.priority) - priorityWeight(a.ticket.priority);
      if (weight !== 0) return weight;
      const activity = lastActivityMs(b.ticket) - lastActivityMs(a.ticket);
      if (activity !== 0) return activity;
      return a.ticket.ticket_number - b.ticket.ticket_number;
    });
}

function hasPriority(priority: Ticket["priority"]): boolean {
  return priority === "low" || priority === "medium" || priority === "high";
}

function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
}

function lastActivityMs(ticket: Ticket): number {
  return (
    parseTime(ticket.last_message_at) ?? parseTime(ticket.updated_at) ?? 0
  );
}
