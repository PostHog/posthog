import type { RequestPermissionRequest } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import { resolveUnattendedPermissionRequest } from "./unattended-permission-policy";

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
  kind?: string,
): RequestPermissionRequest {
  return {
    sessionId: "session-1",
    toolCall: {
      toolCallId: "tool-1",
      ...(kind ? { kind } : {}),
      ...(codeToolKind ? { _meta: { codeToolKind } } : {}),
    },
    options,
  } as RequestPermissionRequest;
}

describe("resolveUnattendedPermissionRequest", () => {
  describe("question tool calls", () => {
    it("cancels with an actionable message instead of auto-approving", () => {
      const params = makeParams(
        [{ optionId: "opt-1", name: "Allow", kind: "allow_once" }],
        "question",
      );

      const result = resolveUnattendedPermissionRequest(params);

      expect(result.outcome.outcome).toBe("cancelled");
      const message = result._meta?.message as string;
      expect(typeof message).toBe("string");
      expect(message.length).toBeGreaterThan(0);
      expect(message).toMatch(/no user/i);
      // The operative half: without these the model loops on a tool nobody
      // can answer.
      expect(message).toMatch(/do NOT re-ask/i);
      expect(message).toMatch(/end your turn/i);
    });

    it("parks the question even when both allow_once and allow_always options exist", () => {
      const params = makeParams(
        [
          { optionId: "opt-1", name: "Allow always", kind: "allow_always" },
          { optionId: "opt-2", name: "Allow once", kind: "allow_once" },
        ],
        "question",
      );

      const result = resolveUnattendedPermissionRequest(params);

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
        const result = resolveUnattendedPermissionRequest(makeParams(options));

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

      const result = resolveUnattendedPermissionRequest(makeParams(options));

      expect(result.outcome).toEqual({
        outcome: "selected",
        optionId: "always-1",
      });
    });

    // reject_always first, so passing this requires ranking by kind rather
    // than taking options[0].
    it("prefers reject_once over reject_always when only reject kinds are present", () => {
      const options: Option[] = [
        {
          optionId: "reject-always-1",
          name: "Reject always",
          kind: "reject_always",
        },
        { optionId: "reject-once-1", name: "Reject once", kind: "reject_once" },
      ];

      const result = resolveUnattendedPermissionRequest(makeParams(options));

      expect(result.outcome).toEqual({
        outcome: "selected",
        optionId: "reject-once-1",
      });
    });

    it("falls back to the first option when no reject_once exists either", () => {
      const options: Option[] = [
        {
          optionId: "reject-always-1",
          name: "Reject always",
          kind: "reject_always",
        },
        {
          optionId: "reject-always-2",
          name: "Reject always too",
          kind: "reject_always",
        },
      ];

      const result = resolveUnattendedPermissionRequest(makeParams(options));

      expect(result.outcome).toEqual({
        outcome: "selected",
        optionId: "reject-always-1",
      });
    });
  });

  // A plan approval's options are session modes, and buildExitPlanModePermissionOptions
  // puts the mode to continue in at index 0. Ranking by kind would pick the sole
  // allow_once ("default"), downgrading an unattended run to interactive and
  // persisting that mode into the repo's local settings.
  describe("plan approval (switch_mode)", () => {
    const exitPlanModeOptions: Option[] = [
      {
        optionId: "auto",
        name: 'Yes, continue in "auto" mode',
        kind: "allow_always",
      },
      {
        optionId: "acceptEdits",
        name: "Yes, and auto-accept edits",
        kind: "allow_always",
      },
      {
        optionId: "default",
        name: "Yes, and manually approve edits",
        kind: "allow_once",
      },
      {
        optionId: "reject_with_feedback",
        name: "No, and tell the agent what to do differently",
        kind: "reject_once",
      },
    ];

    it("continues in the mode the run started in rather than switching to default", () => {
      const result = resolveUnattendedPermissionRequest(
        makeParams(exitPlanModeOptions, undefined, "switch_mode"),
      );

      expect(result.outcome).toEqual({
        outcome: "selected",
        optionId: "auto",
      });
    });

    it("continues in bypassPermissions when that is the mode in front", () => {
      const result = resolveUnattendedPermissionRequest(
        makeParams(
          [
            {
              optionId: "bypassPermissions",
              name: "Yes, continue bypassing all permissions",
              kind: "allow_always",
            },
            ...exitPlanModeOptions,
          ],
          undefined,
          "switch_mode",
        ),
      );

      expect(result.outcome).toEqual({
        outcome: "selected",
        optionId: "bypassPermissions",
      });
    });

    it("still parks a question even when the tool call is a mode switch", () => {
      const result = resolveUnattendedPermissionRequest(
        makeParams(exitPlanModeOptions, "question", "switch_mode"),
      );

      expect(result.outcome.outcome).toBe("cancelled");
    });
  });

  describe("empty options", () => {
    it("cancels when the options array is empty", () => {
      const result = resolveUnattendedPermissionRequest(makeParams([]));

      expect(result.outcome).toEqual({ outcome: "cancelled" });
    });

    it("cancels a plan approval with no options", () => {
      const result = resolveUnattendedPermissionRequest(
        makeParams([], undefined, "switch_mode"),
      );

      expect(result.outcome).toEqual({ outcome: "cancelled" });
    });
  });
});
