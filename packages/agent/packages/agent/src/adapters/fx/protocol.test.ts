import type {
  ContentBlock,
  RequestPermissionRequest,
} from "@agentclientprotocol/sdk";
import { readMcpToolDescriptor } from "@posthog/agent-contracts";
import { describe, expect, it } from "vitest";
import {
  fromFxUsage,
  gatewayFailureError,
  toFxPosthogMode,
  toFxPrompt,
  toPosthogPermissionRequest,
  withPosthogToolMeta,
} from "./protocol";

function permissionRequest(
  toolCall: Partial<RequestPermissionRequest["toolCall"]>,
): RequestPermissionRequest {
  return {
    sessionId: "session-1",
    toolCall: { toolCallId: "call-1", ...toolCall },
    options: [
      { optionId: "allow_once", name: "Allow once", kind: "allow_once" },
      { optionId: "allow_always", name: "Allow", kind: "allow_always" },
      { optionId: "reject_once", name: "Reject", kind: "reject_once" },
    ],
  };
}

describe("fx protocol translation", () => {
  it.each([
    { requested: "default", posthog: "default" },
    { requested: "acceptEdits", posthog: "default" },
    { requested: "auto", posthog: "default" },
    { requested: "full-access", posthog: "full-access" },
    { requested: "bypassPermissions", posthog: "full-access" },
  ])(
    "runs PostHog mode $requested as $posthog so the server keeps approval control",
    ({ requested, posthog }) => {
      expect(toFxPosthogMode(requested)).toBe(posthog);
    },
  );

  it.each(["read-only", "plan", "yolo"])(
    "rejects mode %s that fx cannot enforce",
    (requested) => {
      expect(toFxPosthogMode(requested)).toBeNull();
    },
  );

  it("exposes fx MCP identity where the server's permission gates read it", () => {
    const meta = withPosthogToolMeta(
      { fx: { toolCall: { internal: false } } },
      "other",
      { server: "posthog", tool: "exec" },
    );

    expect(readMcpToolDescriptor(meta)).toEqual({
      server: "posthog",
      tool: "exec",
    });
  });

  it.each([
    {
      name: "a top-level command",
      rawInput: { action: "run", command: "git push" },
    },
    {
      name: "a nested request command",
      rawInput: { action: "run", request: { command: "git push" } },
    },
  ])("exposes $name where the publish block reads it", ({ rawInput }) => {
    const request = toPosthogPermissionRequest(
      permissionRequest({ kind: "execute", rawInput }),
      null,
    );

    expect(request.toolCall._meta).toEqual({ toolName: "Bash" });
    expect(request.toolCall.rawInput).toMatchObject({
      command: "git push",
    });
  });

  it("drops fx session grants so every call returns to the server", () => {
    const request = toPosthogPermissionRequest(
      permissionRequest({ kind: "other" }),
      { server: "posthog", tool: "exec" },
    );

    expect(request.options.map((option) => option.kind)).toEqual([
      "allow_once",
      "reject_once",
    ]);
  });

  it.each([
    {
      name: "a cloud attachment link",
      prompt: [
        { type: "text", text: "Read this" },
        { type: "resource_link", uri: "file:///tmp/a.csv", name: "a.csv" },
      ],
      meta: {},
      expected: [
        "Read this",
        "Attached workspace file (read it from disk): /tmp/a.csv",
      ],
    },
    {
      name: "PR context",
      prompt: [{ type: "text", text: "Fix it" }],
      meta: { prContext: "PR #1" },
      expected: ["PR #1", "Fix it"],
    },
    {
      name: "a local skill invocation",
      prompt: [{ type: "text", text: "/deploy now" }],
      meta: { localSkillContext: "Deploy skill", localSkillName: "deploy" },
      expected: ["Deploy skill"],
    },
    {
      name: "a local skill without its name",
      prompt: [{ type: "text", text: "/deploy now" }],
      meta: { localSkillContext: "Deploy skill" },
      expected: ["Deploy skill", "/deploy now"],
    },
    {
      name: "PR context and a local skill",
      prompt: [{ type: "text", text: "/deploy" }],
      meta: {
        prContext: "PR #1",
        localSkillContext: "Deploy skill",
        localSkillName: "deploy",
      },
      expected: ["PR #1", "Deploy skill"],
    },
  ] satisfies {
    name: string;
    prompt: ContentBlock[];
    meta: Record<string, string>;
    expected: string[];
  }[])("forwards $name to fx as text", ({ prompt, meta, expected }) => {
    const blocks = toFxPrompt(prompt, meta);

    expect(blocks.map((block) => block.type === "text" && block.text)).toEqual(
      expected,
    );
  });

  it.each([
    {
      message: 'API Error: 429 {"error":{"message":"rate limited"}}',
      classification: "upstream_provider_failure",
    },
    {
      message: "API Error: 402 This agent run reached its spend limit",
      classification: "task_spend_limit",
    },
    {
      message: 'API Error: 400 {"error":{"message":"bad tool schema"}}',
      classification: "upstream_request_rejected",
    },
    {
      message: "API Error: Connection error",
      classification: "upstream_connection_error",
    },
  ])(
    "classifies the gateway failure $message as $classification",
    ({ message, classification }) => {
      expect(gatewayFailureError(message, null).data).toMatchObject({
        classification,
      });
    },
  );

  it.each([
    {
      name: "full usage",
      usage: {
        inputTokens: 100,
        outputTokens: 20,
        cacheReadTokens: 50,
        cacheWriteTokens: 5,
        reasoningTokens: 7,
      },
      expected: {
        inputTokens: 100,
        outputTokens: 20,
        cachedReadTokens: 50,
        cachedWriteTokens: 5,
        thoughtTokens: 7,
        totalTokens: 175,
      },
    },
    {
      name: "partial usage",
      usage: { inputTokens: 100, outputTokens: 20 },
      expected: {
        inputTokens: 100,
        outputTokens: 20,
        cachedReadTokens: 0,
        cachedWriteTokens: 0,
        thoughtTokens: 0,
        totalTokens: 120,
      },
    },
    { name: "empty usage", usage: {}, expected: null },
  ])("maps fx $name to ACP usage", ({ usage, expected }) => {
    expect(fromFxUsage(usage)).toEqual(expected);
  });
});
