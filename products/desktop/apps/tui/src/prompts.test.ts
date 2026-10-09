import { describe, expect, it } from "vitest";
import {
  type AgentPrompt,
  promptReply,
  promptSheet,
  wantsText,
} from "./prompts";

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

const question: AgentPrompt = {
  kind: "acp",
  request: {
    taskRunId: "local-1",
    toolCallId: "q1",
    title: "Which channel?",
    options: [
      { optionId: "option_0", name: "npm", kind: "allow_once" },
      { optionId: "option_1", name: "Homebrew", kind: "allow_once" },
    ],
    questions: [
      {
        question: "Which channel?",
        header: "Channel",
        options: [
          { label: "npm", description: "Needs Node" },
          { label: "Homebrew", description: "Needs a tap" },
        ],
      },
      {
        question: "How often?",
        options: [{ label: "On merge" }, { label: "By hand" }],
      },
    ],
  },
};

describe("promptSheet", () => {
  it("offers a Claude Code permission's own options", () => {
    const sheet = promptSheet(acp);
    expect(sheet.title).toBe("Run pnpm test");
    expect(sheet.items.map((item) => item.label)).toEqual(["Allow", "Reject"]);
  });

  it("asks a Claude Code question one step at a time, with each option's description", () => {
    const first = promptSheet(question, 0);
    expect(first.title).toBe("Which channel?");
    expect(first.items).toEqual([
      { label: "npm", detail: "Needs Node" },
      { label: "Homebrew", detail: "Needs a tap" },
    ]);
    expect(first.footer).toContain("1 of 2");
    expect(promptSheet(question, 1).title).toBe("How often?");
  });
});

describe("promptReply", () => {
  it("answers a Claude Code question with every question's picked label", () => {
    const partial = promptReply(question, 1, {});
    expect(partial).toMatchObject({
      answers: { "Which channel?": "Homebrew" },
    });
    const reply = promptReply(
      question,
      0,
      partial.kind === "acp" ? partial.answers : undefined,
    );
    expect(reply).toEqual({
      kind: "acp",
      taskRunId: "local-1",
      toolCallId: "q1",
      optionId: "option_1",
      answers: { "Which channel?": "Homebrew", "How often?": "On merge" },
    });
  });

  it("carries the feedback typed for an option that asks for it", () => {
    const feedback: AgentPrompt = {
      ...acp,
      request: {
        ...acp.request,
        options: [
          acp.request.options[0],
          {
            optionId: "reject",
            name: "No, and tell the agent what to do differently",
            kind: "reject_once",
            _meta: { customInput: true },
          },
        ],
      },
    };
    expect(wantsText(feedback, 0)).toBe(false);
    expect(wantsText(feedback, 1)).toBe(true);
    // The option carries its own text field, filled with what was typed so far.
    expect(promptSheet(feedback, 0, "use pn").items[1]).toMatchObject({
      input: {
        placeholder: expect.stringContaining("what to do instead"),
        text: "use pn",
      },
    });
    expect(promptSheet(feedback, 0).items[0].input).toBeUndefined();
    expect(promptReply(feedback, 1, {}, "use pnpm")).toEqual({
      kind: "acp",
      taskRunId: "local-1",
      toolCallId: "tc1",
      optionId: "reject",
      customInput: "use pnpm",
    });
  });

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
