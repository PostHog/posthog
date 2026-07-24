import type { RequestPermissionRequest } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import { resolvePermissionRequest } from "./permission-policy";

// These option/toolCall shapes mirror the relevant fields of
// @agentclientprotocol/sdk's RequestPermissionRequest/RequestPermissionResponse,
// trimmed to the fields the pure policy function reads.

interface Option {
  optionId: string;
  name: string;
  kind: "allow_once" | "allow_always" | "reject_once" | "reject_always";
}

function makeParams(
  options: Option[],
  codeToolKind?: string,
): RequestPermissionRequest {
  return {
    sessionId: "session-1",
    toolCall: {
      toolCallId: "tool-1",
      ...(codeToolKind ? { _meta: { codeToolKind } } : {}),
    },
    options,
  } as RequestPermissionRequest;
}

describe("resolvePermissionRequest", () => {
  describe("question tool calls", () => {
    it("cancels with an actionable message instead of auto-approving", () => {
      const params = makeParams(
        [{ optionId: "opt-1", name: "Allow", kind: "allow_once" }],
        "question",
      );

      const result = resolvePermissionRequest(params);

      expect(result.outcome.outcome).toBe("cancelled");
      const message = result._meta?.message as string;
      expect(typeof message).toBe("string");
      expect(message.length).toBeGreaterThan(0);
      expect(message).toMatch(/no user/i);
    });

    it("parks the question even when both allow_once and allow_always options exist", () => {
      const params = makeParams(
        [
          { optionId: "opt-1", name: "Allow always", kind: "allow_always" },
          { optionId: "opt-2", name: "Allow once", kind: "allow_once" },
        ],
        "question",
      );

      const result = resolvePermissionRequest(params);

      expect(result.outcome.outcome).toBe("cancelled");
      expect(result._meta?.message).toMatch(/no user/i);
    });
  });

  describe("auto-approval", () => {
    it.each([
      {
        label: "allow_always listed first, allow_once second",
        options: [
          {
            optionId: "always-1",
            name: "Allow always",
            kind: "allow_always" as const,
          },
          {
            optionId: "once-1",
            name: "Allow once",
            kind: "allow_once" as const,
          },
        ],
        expectedOptionId: "once-1",
      },
      {
        label: "allow_once listed first, allow_always second",
        options: [
          {
            optionId: "once-1",
            name: "Allow once",
            kind: "allow_once" as const,
          },
          {
            optionId: "always-1",
            name: "Allow always",
            kind: "allow_always" as const,
          },
        ],
        expectedOptionId: "once-1",
      },
    ])(
      "prefers allow_once over allow_always regardless of order ($label)",
      ({ options, expectedOptionId }) => {
        const result = resolvePermissionRequest(makeParams(options));

        expect(result.outcome).toEqual({
          outcome: "selected",
          optionId: expectedOptionId,
        });
      },
    );

    it("selects allow_always when no allow_once option exists", () => {
      const options: Option[] = [
        { optionId: "reject-1", name: "Reject once", kind: "reject_once" },
        { optionId: "always-1", name: "Allow always", kind: "allow_always" },
      ];

      const result = resolvePermissionRequest(makeParams(options));

      expect(result.outcome).toEqual({
        outcome: "selected",
        optionId: "always-1",
      });
    });

    it("falls back to the first option when only reject kinds are present", () => {
      const options: Option[] = [
        { optionId: "reject-once-1", name: "Reject once", kind: "reject_once" },
        {
          optionId: "reject-always-1",
          name: "Reject always",
          kind: "reject_always",
        },
      ];

      const result = resolvePermissionRequest(makeParams(options));

      expect(result.outcome).toEqual({
        outcome: "selected",
        optionId: "reject-once-1",
      });
    });
  });

  describe("empty options", () => {
    it("cancels when the options array is empty", () => {
      const result = resolvePermissionRequest(makeParams([]));

      expect(result.outcome).toEqual({ outcome: "cancelled" });
    });
  });
});
