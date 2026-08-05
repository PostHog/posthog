import type { Ticket } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  type AttentionState,
  classifyAttention,
  rankQueue,
  SLA_AT_RISK_WINDOW_MS,
} from "./attention";

const NOW = new Date("2026-07-15T12:00:00Z");

function iso(offsetMs: number): string {
  return new Date(NOW.getTime() + offsetMs).toISOString();
}

const HOUR = 60 * 60 * 1000;

let ticketNumber = 0;

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  ticketNumber += 1;
  return {
    id: `t-${ticketNumber}`,
    ticket_number: ticketNumber,
    channel_source: "email",
    channel_detail: null,
    distinct_id: "d-1",
    status: "open",
    priority: null,
    assignee: { id: null, type: "", user: null, role: null },
    created_at: iso(-24 * HOUR),
    updated_at: iso(-1 * HOUR),
    message_count: 1,
    last_message_at: iso(-1 * HOUR),
    last_message_text: "hello",
    unread_team_count: 0,
    unread_customer_count: 0,
    session_id: null,
    session_context: null,
    sla_due_at: null,
    snoozed_until: null,
    slack_channel_id: null,
    slack_thread_ts: null,
    slack_team_id: null,
    email_subject: null,
    email_from: null,
    email_to: null,
    cc_participants: null,
    person: null,
    ...overrides,
  } as Ticket;
}

describe("classifyAttention", () => {
  it.each<[string, Partial<Ticket>, AttentionState]>([
    ["breached SLA", { sla_due_at: iso(-1 * HOUR) }, "sla-breached"],
    [
      "customer replied while pending",
      { status: "pending", unread_team_count: 2 },
      "customer-replied",
    ],
    [
      "customer replied while on hold",
      { status: "on_hold", unread_team_count: 1 },
      "customer-replied",
    ],
    [
      "SLA due within the window",
      { sla_due_at: iso(SLA_AT_RISK_WINDOW_MS - 1) },
      "sla-at-risk",
    ],
    [
      "snooze elapsed",
      { status: "open", snoozed_until: iso(-1) },
      "snooze-elapsed",
    ],
    [
      "still snoozed",
      { status: "open", snoozed_until: iso(1 * HOUR) },
      "snoozed",
    ],
    ["new without priority", { status: "new" }, "untriaged"],
    ["new with priority", { status: "new", priority: "high" }, "in-progress"],
    ["open in progress", { status: "open", priority: "low" }, "in-progress"],
    [
      "pending without unread",
      { status: "pending" },
      "waiting-on-customer",
    ],
  ])("classifies %s", (_name, overrides, expected) => {
    expect(classifyAttention(makeTicket(overrides), NOW)).toBe(expected);
  });

  it("prefers breached SLA over a customer reply", () => {
    const ticket = makeTicket({
      status: "pending",
      unread_team_count: 3,
      sla_due_at: iso(-1 * HOUR),
    });
    expect(classifyAttention(ticket, NOW)).toBe("sla-breached");
  });

  it("prefers a customer reply over an at-risk SLA", () => {
    const ticket = makeTicket({
      status: "pending",
      unread_team_count: 1,
      sla_due_at: iso(1 * HOUR),
    });
    expect(classifyAttention(ticket, NOW)).toBe("customer-replied");
  });

  it("treats an SLA outside the window as not at risk", () => {
    const ticket = makeTicket({
      sla_due_at: iso(SLA_AT_RISK_WINDOW_MS + HOUR),
    });
    expect(classifyAttention(ticket, NOW)).toBe("in-progress");
  });

  it("treats snoozed_until exactly now as elapsed", () => {
    const ticket = makeTicket({ snoozed_until: iso(0) });
    expect(classifyAttention(ticket, NOW)).toBe("snooze-elapsed");
  });
});

describe("rankQueue", () => {
  it("excludes resolved tickets", () => {
    const ranked = rankQueue(
      [makeTicket({ status: "resolved" }), makeTicket({ status: "open" })],
      NOW,
    );
    expect(ranked).toHaveLength(1);
    expect(ranked[0].ticket.status).toBe("open");
  });

  // The plan's flagship acceptance criterion: a ticket whose customer just
  // replied outranks an equivalent untouched new ticket.
  it("ranks a customer reply above an equivalent new ticket", () => {
    const replied = makeTicket({
      status: "pending",
      unread_team_count: 1,
      last_message_at: iso(-4 * HOUR),
    });
    const fresh = makeTicket({
      status: "new",
      last_message_at: iso(-5 * 60 * 1000),
    });
    const ranked = rankQueue([fresh, replied], NOW);
    expect(ranked.map((r) => r.state)).toEqual([
      "customer-replied",
      "untriaged",
    ]);
  });

  it("orders tiers: breached, replied, at-risk, snooze-elapsed, untriaged, in-progress, waiting, snoozed", () => {
    const tickets = [
      makeTicket({ status: "open", snoozed_until: iso(2 * HOUR) }),
      makeTicket({ status: "pending" }),
      makeTicket({ status: "open", priority: "medium" }),
      makeTicket({ status: "new" }),
      makeTicket({ status: "open", snoozed_until: iso(-1 * HOUR) }),
      makeTicket({ status: "open", sla_due_at: iso(1 * HOUR) }),
      makeTicket({ status: "on_hold", unread_team_count: 1 }),
      makeTicket({ status: "open", sla_due_at: iso(-1 * HOUR) }),
    ];
    const ranked = rankQueue(tickets, NOW);
    expect(ranked.map((r) => r.state)).toEqual([
      "sla-breached",
      "customer-replied",
      "sla-at-risk",
      "snooze-elapsed",
      "untriaged",
      "in-progress",
      "waiting-on-customer",
      "snoozed",
    ]);
  });

  // Null priority must not sort as lowest by accident — unknown sits between
  // medium and low, so triage debt can't hide at the bottom.
  it("ranks unknown priority above low within a tier", () => {
    const low = makeTicket({ status: "open", priority: "low" });
    const unknown = makeTicket({ status: "open", priority: null });
    const high = makeTicket({ status: "open", priority: "high" });
    const ranked = rankQueue([low, unknown, high], NOW);
    expect(ranked.map((r) => r.ticket.priority ?? "unknown")).toEqual([
      "high",
      "unknown",
      "low",
    ]);
  });

  it("breaks priority ties by latest activity, then ticket number", () => {
    const older = makeTicket({
      status: "open",
      priority: "high",
      last_message_at: iso(-3 * HOUR),
    });
    const newer = makeTicket({
      status: "open",
      priority: "high",
      last_message_at: iso(-1 * HOUR),
    });
    const ranked = rankQueue([older, newer], NOW);
    expect(ranked[0].ticket.id).toBe(newer.id);

    const twinA = makeTicket({
      status: "open",
      priority: "high",
      last_message_at: iso(-1 * HOUR),
    });
    const twinB = makeTicket({
      status: "open",
      priority: "high",
      last_message_at: iso(-1 * HOUR),
    });
    const twins = rankQueue([twinB, twinA], NOW);
    expect(twins[0].ticket.ticket_number).toBeLessThan(
      twins[1].ticket.ticket_number,
    );
  });

  it("is deterministic for a fixed now", () => {
    const tickets = [
      makeTicket({ status: "new" }),
      makeTicket({ status: "pending", unread_team_count: 1 }),
      makeTicket({ status: "open", priority: "high" }),
      makeTicket({ status: "open", sla_due_at: iso(30 * 60 * 1000) }),
    ];
    const a = rankQueue([...tickets], NOW).map((r) => r.ticket.id);
    const b = rankQueue([...tickets].reverse(), NOW).map((r) => r.ticket.id);
    expect(a).toEqual(b);
  });

  it("does not mutate its input", () => {
    const tickets = [
      makeTicket({ status: "open" }),
      makeTicket({ status: "new" }),
    ];
    const original = [...tickets];
    rankQueue(tickets, NOW);
    expect(tickets).toEqual(original);
  });
});
