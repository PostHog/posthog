import type { SupportTicket } from "@posthog/api-client/posthog-client";

export const SLA_AT_RISK_WINDOW_MS = 60 * 60 * 1000;

export type TicketSlaState = "none" | "on-track" | "at-risk" | "breached";

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
