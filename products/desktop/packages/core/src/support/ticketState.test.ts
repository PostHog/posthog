import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  isTicketSnoozed,
  SLA_AT_RISK_WINDOW_MS,
  type TicketSlaState,
  ticketSlaState,
} from "./ticketState";

const NOW = Date.parse("2026-08-12T12:00:00Z");

function isoAfter(offsetMs: number): string {
  return new Date(NOW + offsetMs).toISOString();
}

describe("support ticket state", () => {
  it.each<[string, string | null, TicketSlaState]>([
    ["no deadline", null, "none"],
    ["an unparseable deadline", "not a date", "none"],
    ["a deadline that passed", isoAfter(-60_000), "breached"],
    ["a deadline exactly now", isoAfter(0), "breached"],
    [
      "a deadline at the at-risk boundary",
      isoAfter(SLA_AT_RISK_WINDOW_MS),
      "at-risk",
    ],
    ["a deadline beyond it", isoAfter(SLA_AT_RISK_WINDOW_MS + 1), "on-track"],
  ])("reads SLA state with %s", (_case, slaDueAt, expected) => {
    expect(ticketSlaState({ sla_due_at: slaDueAt } as SupportTicket, NOW)).toBe(
      expected,
    );
  });

  it.each<[string, string | null, boolean]>([
    ["no snooze", null, false],
    ["a future snooze", isoAfter(1), true],
    ["a snooze that just elapsed", isoAfter(-1), false],
    ["an unparseable snooze", "whenever", false],
  ])("detects snoozing with %s", (_case, snoozedUntil, expected) => {
    expect(
      isTicketSnoozed({ snoozed_until: snoozedUntil } as SupportTicket, NOW),
    ).toBe(expected);
  });
});
