import type {
  SupportTicket,
  SupportTicketUpdate,
} from "@posthog/api-client/posthog-client";

/** How long before its deadline a ticket counts as at risk rather than on track. */
export const SLA_AT_RISK_WINDOW_MS = 60 * 60 * 1000;

export type TicketSlaState = "none" | "on-track" | "at-risk" | "breached";

export type TicketAttention =
  | "customer-replied"
  | "sla-breached"
  | "sla-at-risk"
  | "untriaged"
  | "snoozed"
  | "waiting-on-customer"
  | "in-progress"
  | "resolved";

const ACTIVE_AFTER_CUSTOMER_REPLY: ReadonlySet<string> = new Set([
  "pending",
  "on_hold",
]);

export function ticketSlaState(
  ticket: Pick<SupportTicket, "sla_due_at">,
  now: number,
): TicketSlaState {
  if (!ticket.sla_due_at) {
    return "none";
  }
  const dueAt = Date.parse(ticket.sla_due_at);
  if (Number.isNaN(dueAt)) {
    return "none";
  }
  if (dueAt <= now) {
    return "breached";
  }
  return dueAt - now <= SLA_AT_RISK_WINDOW_MS ? "at-risk" : "on-track";
}

/**
 * Why a ticket wants attention, in the order a support engineer would triage.
 *
 * `customer-replied` outranks the SLA states because it is the signal that the
 * ball came back to the team: a ticket parked awaiting the customer becomes
 * actionable the moment they answer, regardless of how much SLA is left.
 */
export function ticketAttention(
  ticket: Pick<
    SupportTicket,
    "status" | "priority" | "sla_due_at" | "snoozed_until" | "unread_team_count"
  >,
  now: number,
): TicketAttention {
  if (ticket.status === "resolved") {
    return "resolved";
  }

  const hasUnread = (ticket.unread_team_count ?? 0) > 0;
  const status = ticket.status ?? "new";

  if (hasUnread && ACTIVE_AFTER_CUSTOMER_REPLY.has(status)) {
    return "customer-replied";
  }

  const sla = ticketSlaState(ticket, now);
  if (sla === "breached") {
    return "sla-breached";
  }
  if (sla === "at-risk") {
    return "sla-at-risk";
  }

  if (isTicketSnoozed(ticket, now)) {
    return "snoozed";
  }
  if (status === "new" || ticket.priority == null) {
    return "untriaged";
  }
  if (status === "pending" || status === "on_hold") {
    return "waiting-on-customer";
  }
  return "in-progress";
}

export function isTicketSnoozed(
  ticket: Pick<SupportTicket, "snoozed_until">,
  now: number,
): boolean {
  if (!ticket.snoozed_until) {
    return false;
  }
  const until = Date.parse(ticket.snoozed_until);
  return !Number.isNaN(until) && until > now;
}

/**
 * What a triage write will look like once the server has applied its own rules,
 * so an optimistic cache write matches the response that follows it.
 *
 * The backend moves a ticket to `on_hold` when a snooze is set and back to
 * `open` when one is cleared, but only when the caller did not send a status of
 * its own. Predicting that here keeps a snoozed row from flicking through its
 * old status on the way to the server's answer.
 *
 * Assignment is deliberately not predicted: the write takes a user or role
 * reference while a ticket carries the resolved assignee, and inventing that
 * resolution locally would show a name the server never confirmed.
 */
export function predictTicketUpdate(
  ticket: SupportTicket,
  updates: SupportTicketUpdate,
): SupportTicket {
  const predicted: SupportTicket = { ...ticket };

  if (updates.status !== undefined) {
    predicted.status = updates.status;
  }
  if (updates.priority !== undefined) {
    predicted.priority = updates.priority;
  }
  if (updates.snoozed_until !== undefined) {
    predicted.snoozed_until = updates.snoozed_until;
  }
  if (updates.tags !== undefined) {
    predicted.tags = updates.tags;
  }

  if (updates.status !== undefined || updates.snoozed_until === undefined) {
    return predicted;
  }

  const hadSnooze = ticket.snoozed_until != null;
  const hasSnooze = updates.snoozed_until != null;

  if (!hadSnooze && hasSnooze) {
    predicted.status = "on_hold";
  } else if (hadSnooze && !hasSnooze) {
    predicted.status = "open";
  }

  return predicted;
}
