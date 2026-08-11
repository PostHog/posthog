import type {
  RequestPermissionRequest,
  RequestPermissionResponse,
} from "@agentclientprotocol/sdk";
import { describe, expect, it, vi } from "vitest";
import { QuestionMetaSchema } from "../claude/questions/utils";
import { handleServerRequest } from "./approvals";
import { APP_SERVER_REQUESTS } from "./protocol";

// A fake ACP client whose requestPermission returns queued outcomes positionally.
function fakeClient(outcomes: RequestPermissionResponse["outcome"][]) {
  const calls: RequestPermissionRequest[] = [];
  let next = 0;
  const requestPermission = vi.fn(
    async (
      params: RequestPermissionRequest,
    ): Promise<RequestPermissionResponse> => {
      calls.push(params);
      const outcome = outcomes[next++] ?? { outcome: "cancelled" as const };
      return { outcome };
    },
  );
  return { client: { requestPermission }, calls };
}

const opts = { sessionId: "sess-1" };

describe("handleServerRequest", () => {
  it("maps a requestUserInput question's selected option back to an answer", async () => {
    const { client, calls } = fakeClient([
      { outcome: "selected", optionId: "option_1" },
    ]);

    const params = {
      threadId: "t",
      turnId: "turn",
      itemId: "item-9",
      autoResolutionMs: null,
      questions: [
        {
          id: "q1",
          header: "Pick one",
          question: "Which environment?",
          isOther: false,
          isSecret: false,
          options: [
            { label: "staging", description: "" },
            { label: "production", description: "danger" },
          ],
        },
      ],
    };

    const result = await handleServerRequest(
      APP_SERVER_REQUESTS.TOOL_USER_INPUT,
      params,
      client,
      opts,
    );

    expect(result.handled).toBe(true);
    expect(result.response).toEqual({
      answers: { q1: { answers: ["production"] } },
    });

    expect(calls).toHaveLength(1);
    expect(calls[0].sessionId).toBe("sess-1");
    expect(calls[0].options.map((o) => o.name)).toEqual([
      "staging",
      "production",
    ]);
  });

  it("answers each question in a multi-question request independently", async () => {
    const { client, calls } = fakeClient([
      { outcome: "selected", optionId: "option_0" },
      { outcome: "selected", optionId: "option_1" },
    ]);

    const params = {
      threadId: "t",
      turnId: "turn",
      itemId: "item-2",
      autoResolutionMs: null,
      questions: [
        {
          id: "q1",
          header: "Env",
          question: "Which environment?",
          isOther: false,
          isSecret: false,
          options: [
            { label: "staging", description: "" },
            { label: "production", description: "" },
          ],
        },
        {
          id: "q2",
          header: "Region",
          question: "Which region?",
          isOther: false,
          isSecret: false,
          options: [
            { label: "us", description: "" },
            { label: "eu", description: "" },
          ],
        },
      ],
    };

    const result = await handleServerRequest(
      APP_SERVER_REQUESTS.TOOL_USER_INPUT,
      params,
      client,
      opts,
    );

    expect(result.handled).toBe(true);
    expect(result.response).toEqual({
      answers: {
        q1: { answers: ["staging"] },
        q2: { answers: ["eu"] },
      },
    });
    expect(calls).toHaveLength(2);
    expect(calls.map((c) => c.toolCall?.title)).toEqual([
      "Which environment?",
      "Which region?",
    ]);
  });

  it("skips a free-text question (no options) with a well-formed empty answer", async () => {
    const { client, calls } = fakeClient([
      { outcome: "selected", optionId: "option_0" },
    ]);

    const params = {
      threadId: "t",
      turnId: "turn",
      itemId: "item-3",
      autoResolutionMs: null,
      questions: [
        {
          id: "free",
          header: "Notes",
          question: "Anything else?",
          isOther: true,
          isSecret: false,
          options: [],
        },
        {
          id: "pick",
          header: "Env",
          question: "Which environment?",
          isOther: false,
          isSecret: false,
          options: [{ label: "staging", description: "" }],
        },
      ],
    };

    const result = await handleServerRequest(
      APP_SERVER_REQUESTS.TOOL_USER_INPUT,
      params,
      client,
      opts,
    );

    expect(result.handled).toBe(true);
    expect(result.response).toEqual({
      answers: {
        free: { answers: [] },
        pick: { answers: ["staging"] },
      },
    });
    // The free-text question never reaches requestPermission.
    expect(calls).toHaveLength(1);
    expect(calls[0].toolCall?.title).toBe("Which environment?");
  });

  it("carries a QuestionMetaSchema-valid questions array so the host card renders", async () => {
    const { client, calls } = fakeClient([
      { outcome: "selected", optionId: "option_0" },
    ]);

    const params = {
      threadId: "t",
      turnId: "turn",
      itemId: "item-1",
      autoResolutionMs: null,
      questions: [
        {
          id: "q1",
          header: "Environment",
          question: "Which environment?",
          isOther: false,
          isSecret: false,
          options: [
            { label: "staging", description: "" },
            { label: "production", description: "danger" },
          ],
        },
      ],
    };

    await handleServerRequest(
      APP_SERVER_REQUESTS.TOOL_USER_INPUT,
      params,
      client,
      opts,
    );

    // A bare `{ header }` _meta fails QuestionMetaSchema, rendering an empty card.
    const parsed = QuestionMetaSchema.safeParse(calls[0].toolCall?._meta);
    expect(parsed.success).toBe(true);
    expect(parsed.data?.questions).toEqual([
      {
        question: "Which environment?",
        header: "Environment",
        // The non-empty description rides along; the empty one is dropped.
        options: [
          { label: "staging" },
          { label: "production", description: "danger" },
        ],
      },
    ]);
  });

  it("defaults a cancelled question to an empty answer", async () => {
    const { client } = fakeClient([{ outcome: "cancelled" }]);

    const params = {
      threadId: "t",
      turnId: "turn",
      itemId: "item-1",
      autoResolutionMs: null,
      questions: [
        {
          id: "q1",
          header: "h",
          question: "q?",
          isOther: false,
          isSecret: false,
          options: [{ label: "a", description: "" }],
        },
      ],
    };

    const result = await handleServerRequest(
      APP_SERVER_REQUESTS.TOOL_USER_INPUT,
      params,
      client,
      opts,
    );

    expect(result.response).toEqual({ answers: { q1: { answers: [] } } });
  });

  it.each([
    // "allow_once" grants for the turn, not session-wide; reject grants nothing.
    { optionId: "allow", expected: { network: { enabled: true } } },
    { optionId: "reject", expected: {} },
  ])(
    "resolves a permission approval on $optionId",
    async ({ optionId, expected }) => {
      const { client } = fakeClient([{ outcome: "selected", optionId }]);

      const params = {
        threadId: "t",
        turnId: "turn",
        itemId: "perm-1",
        environmentId: null,
        startedAtMs: 0,
        cwd: "/repo",
        reason: "needs network",
        permissions: {
          network: { enabled: true },
          fileSystem: null,
        },
      };

      const result = await handleServerRequest(
        APP_SERVER_REQUESTS.PERMISSIONS_APPROVAL,
        params,
        client,
        opts,
      );

      expect(result.handled).toBe(true);
      expect(result.response).toEqual({
        permissions: expected,
        scope: "turn",
      });
    },
  );

  it("fails closed to the safe default when a payload is malformed", async () => {
    const { client } = fakeClient([{ outcome: "selected", optionId: "allow" }]);
    const result = await handleServerRequest(
      APP_SERVER_REQUESTS.PERMISSIONS_APPROVAL,
      null,
      client,
      opts,
    );
    expect(result).toEqual({
      handled: true,
      response: { permissions: {}, scope: "turn" },
    });
  });

  it.each([
    { optionId: "accept", action: "accept", content: {} },
    { optionId: "decline", action: "decline", content: null },
  ])(
    "resolves an elicitation on $optionId",
    async ({ optionId, action, content }) => {
      const { client } = fakeClient([{ outcome: "selected", optionId }]);

      const result = await handleServerRequest(
        APP_SERVER_REQUESTS.MCP_ELICITATION,
        {
          threadId: "t",
          turnId: "turn",
          serverName: "posthog",
          mode: "form",
          message: "Confirm the export",
        },
        client,
        opts,
      );

      expect(result.handled).toBe(true);
      expect(result.response).toEqual({ action, content, _meta: null });
    },
  );

  it("enriches an elicitation with the in-flight MCP tool call so the host renders the real tool", async () => {
    const { client, calls } = fakeClient([
      { outcome: "selected", optionId: "accept" },
    ]);

    await handleServerRequest(
      APP_SERVER_REQUESTS.MCP_ELICITATION,
      {
        threadId: "t",
        turnId: "turn",
        serverName: "posthog",
        mode: "form",
        message: 'Allow the posthog MCP server to run tool "exec"?',
      },
      client,
      {
        ...opts,
        resolveMcpToolCall: (serverName) =>
          serverName === "posthog"
            ? {
                server: "posthog",
                tool: "exec",
                args: { command: "search project|insight" },
              }
            : undefined,
      },
    );

    expect(calls[0].toolCall).toMatchObject({
      toolCallId: "posthog:elicitation",
      rawInput: { command: "search project|insight" },
      _meta: {
        posthog: {
          toolName: "mcp__posthog__exec",
          mcp: { server: "posthog", tool: "exec" },
        },
      },
    });
  });

  it("falls back to codex's generic elicitation text when no MCP call correlates", async () => {
    const { client, calls } = fakeClient([
      { outcome: "selected", optionId: "decline" },
    ]);

    await handleServerRequest(
      APP_SERVER_REQUESTS.MCP_ELICITATION,
      {
        threadId: "t",
        turnId: "t",
        serverName: "posthog",
        mode: "form",
        message: "Confirm",
      },
      client,
      // resolveMcpToolCall absent (e.g. server mismatch) → no enrichment.
      opts,
    );

    expect(calls[0].toolCall).not.toHaveProperty("_meta");
    expect(calls[0].toolCall).toMatchObject({
      toolCallId: "posthog:elicitation",
      title: "Confirm",
    });
  });

  it("returns handled:false for the simple command approval (caller owns it)", async () => {
    const { client, calls } = fakeClient([]);

    const result = await handleServerRequest(
      APP_SERVER_REQUESTS.COMMAND_APPROVAL,
      { itemId: "x", command: "ls" },
      client,
      opts,
    );

    expect(result).toEqual({ handled: false, response: undefined });
    expect(calls).toHaveLength(0);
  });

  it("returns handled:false for an unknown method", async () => {
    const { client } = fakeClient([]);

    const result = await handleServerRequest(
      "some/unknown/method",
      {},
      client,
      opts,
    );

    expect(result).toEqual({ handled: false, response: undefined });
  });
});
