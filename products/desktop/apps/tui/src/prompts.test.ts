import { describe, expect, it } from "vitest";
import { type AgentPrompt, promptReply, promptSheet } from "./prompts";

const dialog = (request: Record<string, unknown>): AgentPrompt =>
  ({
    kind: "dialog",
    request: {
      type: "extension_ui_request",
      id: "d1",
      title: "Title",
      ...request,
    },
  }) as AgentPrompt;
const permission: AgentPrompt = {
  kind: "permission",
  request: {
    requestId: "p1",
    serverName: "posthog",
    toolName: "query",
    installationId: "i1",
    arguments: {},
  },
};

const acp: AgentPrompt = {
  kind: "acp",
  request: {
    taskRunId: "local-1",
    toolCallId: "tc1",
    title: "Run pnpm test",
    options: [
      { optionId: "allow", name: "Allow", kind: "allow_once" },
      { optionId: "reject", name: "Reject", kind: "reject_once" },
    ],
  },
};

describe("promptSheet", () => {
  it("offers a Claude Code permission's own options", () => {
    const sheet = promptSheet(acp);
    expect(sheet.title).toBe("Run pnpm test");
    expect(sheet.items.map((item) => item.label)).toEqual(["Allow", "Reject"]);
  });
});

describe("promptReply", () => {
  it.each([
    ["the chosen option", 0, "allow"],
    ["the first rejecting option when dismissed", null, "reject"],
  ])("answers a Claude Code permission with %s", (_, answer, optionId) => {
    expect(promptReply(acp, answer)).toEqual({
      kind: "acp",
      taskRunId: "local-1",
      toolCallId: "tc1",
      optionId,
    });
  });

  it.each([
    [
      "a picked option",
      dialog({ method: "select", options: ["a", "b"] }),
      1,
      {
        kind: "dialog",
        response: { type: "extension_ui_response", id: "d1", value: "b" },
      },
    ],
    [
      "yes to a confirm",
      dialog({ method: "confirm", message: "Sure?" }),
      0,
      {
        kind: "dialog",
        response: { type: "extension_ui_response", id: "d1", confirmed: true },
      },
    ],
    [
      "no to a confirm",
      dialog({ method: "confirm", message: "Sure?" }),
      1,
      {
        kind: "dialog",
        response: { type: "extension_ui_response", id: "d1", confirmed: false },
      },
    ],
    [
      "typed text",
      dialog({ method: "input" }),
      "hello",
      {
        kind: "dialog",
        response: { type: "extension_ui_response", id: "d1", value: "hello" },
      },
    ],
    [
      "a dismissed dialog",
      dialog({ method: "editor" }),
      null,
      {
        kind: "dialog",
        response: { type: "extension_ui_response", id: "d1", cancelled: true },
      },
    ],
    [
      "allow once",
      permission,
      0,
      { kind: "permission", requestId: "p1", decision: "allow" },
    ],
    [
      "a dismissed permission",
      permission,
      null,
      { kind: "permission", requestId: "p1", decision: "reject" },
    ],
  ])("answers %s", (_name, prompt, answer, expected) => {
    expect(promptReply(prompt, answer)).toEqual(expected);
  });
});
