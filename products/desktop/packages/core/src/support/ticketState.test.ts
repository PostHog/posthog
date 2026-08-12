import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  isTicketSnoozed,
  predictTicketUpdate,
  SLA_AT_RISK_WINDOW_MS,
  type TicketAttention,
  type TicketSlaState,
  ticketAttention,
  ticketSlaState,
} from "./ticketState";

const NOW = Date.parse("2026-08-12T12:00:00Z");

function ticket(overrides: Partial<SupportTicket> = {}): SupportTicket {
  return {
    status: "open",
    priority: "medium",
    sla_due_at: null,
    snoozed_until: null,
    unread_team_count: 0,
    ...overrides,
  } as SupportTicket;
}

function isoAfter(offsetMs: number): string {
  return new Date(NOW + offsetMs).toISOString();
}

describe("support ticket state", () => {
  it.each<[string, string | null, TicketSlaState]>([
    ["no deadline", null, "none"],
    ["unparseable deadline", "not a date", "none"],
    ["deadline passed", isoAfter(-60_000), "breached"],
    ["deadline exactly now", isoAfter(0), "breached"],
    [
      "inside the at-risk window",
      isoAfter(SLA_AT_RISK_WINDOW_MS - 1),
      "at-risk",
    ],
    ["at the at-risk boundary", isoAfter(SLA_AT_RISK_WINDOW_MS), "at-risk"],
    [
      "beyond the at-risk window",
      isoAfter(SLA_AT_RISK_WINDOW_MS + 1),
      "on-track",
    ],
  ])("reads SLA state with %s", (_case, slaDueAt, expected) => {
    expect(ticketSlaState(ticket({ sla_due_at: slaDueAt }), NOW)).toBe(
      expected,
    );
  });

  it.each<[string, Partial<SupportTicket>, TicketAttention]>([
    [
      "a customer replied to a pending ticket",
      { status: "pending", unread_team_count: 1 },
      "customer-replied",
    ],
    [
      "a customer replied to a snoozed ticket",
      { status: "on_hold", unread_team_count: 2 },
      "customer-replied",
    ],
    [
      "a customer reply outranks a breached deadline",
      {
        status: "pending",
        unread_team_count: 1,
        sla_due_at: isoAfter(-60_000),
      },
      "customer-replied",
    ],
    [
      "unread on an open ticket is not a returning customer",
      { status: "open", unread_team_count: 1 },
      "in-progress",
    ],
    ["a deadline has passed", { sla_due_at: isoAfter(-1) }, "sla-breached"],
    [
      "a deadline is close",
      { sla_due_at: isoAfter(SLA_AT_RISK_WINDOW_MS - 1) },
      "sla-at-risk",
    ],
    [
      "a snooze is still running",
      { snoozed_until: isoAfter(60_000) },
      "snoozed",
    ],
    [
      "a snooze has elapsed",
      { status: "on_hold", snoozed_until: isoAfter(-60_000) },
      "waiting-on-customer",
    ],
    ["the ticket is new", { status: "new" }, "untriaged"],
    ["priority was never set", { status: "open", priority: null }, "untriaged"],
    [
      "the ticket waits on the customer",
      { status: "pending" },
      "waiting-on-customer",
    ],
    ["work is under way", { status: "open" }, "in-progress"],
    [
      "the ticket is resolved despite an unread reply",
      { status: "resolved", unread_team_count: 3 },
      "resolved",
    ],
  ])("ranks attention when %s", (_case, overrides, expected) => {
    expect(ticketAttention(ticket(overrides), NOW)).toBe(expected);
  });

  it.each<[string, string | null, boolean]>([
    ["no snooze", null, false],
    ["a future snooze", isoAfter(1), true],
    ["a snooze that just elapsed", isoAfter(-1), false],
    ["an unparseable snooze", "whenever", false],
  ])("detects snoozing with %s", (_case, snoozedUntil, expected) => {
    expect(isTicketSnoozed(ticket({ snoozed_until: snoozedUntil }), NOW)).toBe(
      expected,
    );
  });

  describe("predicting a triage write", () => {
    it("moves a newly snoozed ticket to on hold", () => {
      const predicted = predictTicketUpdate(ticket({ status: "open" }), {
        snoozed_until: isoAfter(60_000),
      });

      expect(predicted.status).toBe("on_hold");
    });

    it("reopens a ticket whose snooze was cleared", () => {
      const predicted = predictTicketUpdate(
        ticket({ status: "on_hold", snoozed_until: isoAfter(60_000) }),
        { snoozed_until: null },
      );

      expect(predicted.status).toBe("open");
    });

    it("leaves status alone when the caller sets it explicitly", () => {
      const predicted = predictTicketUpdate(ticket({ status: "open" }), {
        snoozed_until: isoAfter(60_000),
        status: "pending",
      });

      expect(predicted.status).toBe("pending");
    });

    it("applies other fields without touching status", () => {
      const predicted = predictTicketUpdate(ticket({ status: "open" }), {
        priority: "high",
      });

      expect(predicted.priority).toBe("high");
      expect(predicted.status).toBe("open");
    });
  });
});
