import { describe, expect, it, vi } from "vitest";
import { modelSheet, parseSlash, piControl, shortModelName } from "./models";

const opus = { provider: "posthog", id: "claude-opus-5-5", name: "Opus 5.5" };
const terra = {
  provider: "posthog",
  id: "gpt-5.6-terra",
  name: "GPT 5.6 Terra",
};

describe("parseSlash", () => {
  it.each([
    ["/model", { command: "model", args: "" }],
    ["  /new  ", { command: "new", args: "" }],
    ["/review the PR", { command: "review", args: "the PR" }],
    ["hello /model", null],
  ])("reads %j", (text, expected) => {
    expect(parseSlash(text)).toEqual(expected);
  });
});

describe("shortModelName", () => {
  it.each([
    ["claude-opus-5-5", "Opus 5.5"],
    ["claude-opus-4-5-20251101", "Opus 4.5"],
    ["gpt-6.1-sol", "Sol 6.1"],
    ["gpt-5.5", "GPT 5.5"],
    ["gpt-5-mini", "GPT 5 Mini"],
    ["google/gemini-3.1-pro-preview-06-05", "Gemini 3.1 Pro Preview"],
    ["moonshotai/kimi-k3", "Kimi 3"],
    ["@cf/zai-org/glm-5.2", "GLM 5.2"],
    ["deepseek-ai/deepseek-v4-flash-0731", "DeepSeek 4 Flash"],
  ])("names %s as %s", (id, name) => {
    expect(shortModelName(id)).toBe(name);
  });
});

describe("modelSheet", () => {
  it("lists the models and ticks the one in use", () => {
    const sheet = modelSheet([terra, opus], opus, "Applies to this chat.");
    expect(sheet.title).toBe("Select model");
    expect(
      sheet.items.map((item) => [item.label, item.current ?? false]),
    ).toEqual([
      ["GPT 5.6 Terra", false],
      ["Opus 5.5", true],
    ]);
  });
});

describe("piControl", () => {
  it("reads the run's harness models, current model and effort, and switches them, over pi/rpc", async () => {
    const personalLogin = {
      provider: "anthropic",
      id: "claude-opus-5-5",
      name: "Claude Opus 5.5",
    };
    const notInCatalog = {
      provider: "posthog",
      id: "gpt-5.2",
      name: "gpt-5.2",
    };
    const sendCommand = vi.fn(
      async ({
        params,
      }: {
        params: { command: { id: string; type: string } };
      }) => {
        const { id, type } = params.command;
        const data =
          type === "get_available_models"
            ? { models: [terra, personalLogin, notInCatalog, opus] }
            : type === "get_state"
              ? { model: terra, thinkingLevel: "medium" }
              : type === "get_available_thinking_levels"
                ? { levels: ["low", "medium", "high"] }
                : undefined;
        return {
          success: true,
          result: { id, type: "response", command: type, success: true, data },
        };
      },
    );
    const control = piControl(sendCommand as never, "t1", "r1");

    expect(await control.models()).toEqual({
      available: [
        { ...terra, name: "Terra 5.6" },
        { ...opus, name: "Opus 5.5" },
      ],
      current: { ...terra, name: "Terra 5.6" },
      effort: "medium",
    });
    expect(await control.efforts()).toEqual({
      available: ["low", "medium", "high"],
      current: "medium",
    });
    await control.setEffort("high");
    expect(sendCommand.mock.calls.at(-1)?.[0].params.command).toMatchObject({
      type: "set_thinking_level",
      level: "high",
    });
    await control.setModel(opus);

    const sent = sendCommand.mock.calls.map(
      ([input]) =>
        input as unknown as {
          method: string;
          taskId: string;
          runId: string;
          params: { command: Record<string, unknown> };
        },
    );
    expect(
      sent.every(
        (input) =>
          input.method === "pi/rpc" &&
          input.taskId === "t1" &&
          input.runId === "r1",
      ),
    ).toBe(true);
    expect(sent.at(-1)?.params.command).toMatchObject({
      type: "set_model",
      provider: "posthog",
      modelId: "claude-opus-5-5",
    });
  });

  it("lists the run's own slash commands", async () => {
    const sendCommand = vi.fn(
      async ({
        params,
      }: {
        params: { command: { id: string; type: string } };
      }) => ({
        success: true,
        result: {
          id: params.command.id,
          type: "response",
          command: params.command.type,
          success: true,
          data: {
            commands: [
              {
                name: "review-pr",
                description: "Review a pull request",
                source: "skill",
                sourceInfo: {},
              },
            ],
          },
        },
      }),
    );

    expect(
      await piControl(sendCommand as never, "t1", "r1").commands(),
    ).toEqual([{ name: "review-pr", description: "Review a pull request" }]);
  });

  it("compacts the run's context with the given focus and reports the sizes", async () => {
    const sendCommand = vi.fn(
      async ({
        params,
      }: {
        params: { command: { id: string; type: string } };
      }) => ({
        success: true,
        result: {
          id: params.command.id,
          type: "response",
          command: params.command.type,
          success: true,
          data: {
            summary: "s",
            firstKeptEntryId: "e9",
            tokensBefore: 150_000,
            estimatedTokensAfter: 32_000,
          },
        },
      }),
    );

    const compaction = await piControl(
      sendCommand as never,
      "t1",
      "r1",
    ).compact("keep the test plan");

    expect(sendCommand.mock.calls[0][0]).toMatchObject({
      method: "pi/rpc",
      params: {
        command: { type: "compact", customInstructions: "keep the test plan" },
      },
    });
    expect(compaction).toEqual({
      tokensBefore: 150_000,
      estimatedTokensAfter: 32_000,
    });
  });

  it("stops the agent's current turn with the command every sandbox agent takes", async () => {
    const sendCommand = vi.fn(async (_input: { method: string }) => ({
      success: true,
    }));

    await piControl(sendCommand as never, "t1", "r1").abort();

    expect(sendCommand.mock.calls[0][0]).toMatchObject({ method: "cancel" });
  });

  it("runs a shell command in the run's sandbox and returns its output", async () => {
    const result = { output: "clean", exitCode: 0, cancelled: false };
    const sendCommand = vi.fn(
      async ({
        params,
      }: {
        params: { command: { id: string; type: string } };
      }) => ({
        success: true,
        result: {
          id: params.command.id,
          type: "response",
          command: params.command.type,
          success: true,
          data: result,
        },
      }),
    );

    expect(
      await piControl(sendCommand as never, "t1", "r1").bash("git status"),
    ).toMatchObject(result);
    expect(sendCommand.mock.calls[0][0]).toMatchObject({
      taskId: "t1",
      runId: "r1",
      params: { command: { type: "bash", command: "git status" } },
    });
  });
});
