import type { Signal } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  conversationsTicketRef,
  supportTicketUrl,
} from "./conversationsTicket";

function makeSignal(overrides: Partial<Signal> = {}): Signal {
  return {
    signal_id: "s1",
    content: "",
    source_product: "conversations",
    source_type: "ticket",
    source_id: "0197-ticket-uuid",
    weight: 1,
    timestamp: "",
    extra: {},
    ...overrides,
  };
}

describe("conversationsTicketRef", () => {
  it.each([
    [
      "the ticket number when the emitter stored one",
      { ticket_number: 4821 },
      4821,
    ],
    [
      "the ticket uuid for evidence stored without a number",
      {},
      "0197-ticket-uuid",
    ],
  ])("resolves to %s", (_label, extra, expected) => {
    expect(conversationsTicketRef(makeSignal(), extra)).toBe(expected);
  });

  it.each([
    ["a non-positive integer", 0],
    ["a non-integer", 12.5],
  ])(
    "falls back to source_id when ticket_number is %s",
    (_label, ticket_number) => {
      expect(conversationsTicketRef(makeSignal(), { ticket_number })).toBe(
        "0197-ticket-uuid",
      );
    },
  );

  it("returns null when neither identifier resolves", () => {
    expect(
      conversationsTicketRef(makeSignal({ source_id: "" }), {}),
    ).toBeNull();
  });
});

describe("supportTicketUrl", () => {
  it.each([
    [
      "a ticket number",
      4821,
      "https://us.posthog.com/project/123/support/tickets/4821",
    ],
    [
      "a ticket uuid",
      "0197-uuid",
      "https://us.posthog.com/project/123/support/tickets/0197-uuid",
    ],
    [
      "an unsafe ticket ref",
      "a/b?c",
      "https://us.posthog.com/project/123/support/tickets/a%2Fb%3Fc",
    ],
  ])(
    "links the source project's ticket page by %s",
    (_label, ref, expected) => {
      expect(supportTicketUrl(ref, { projectId: 123, cloudRegion: "us" })).toBe(
        expected,
      );
    },
  );

  it.each([
    ["project", { projectId: null, cloudRegion: "us" as const }],
    ["region", { projectId: 123, cloudRegion: null }],
  ])(
    "has no destination without a %s to resolve against",
    (_label, options) => {
      expect(supportTicketUrl(4821, options)).toBeNull();
    },
  );
});
