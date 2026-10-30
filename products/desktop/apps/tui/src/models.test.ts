import { describe, expect, it, vi } from "vitest";
import { modelSheet, parseSlash, piControl } from "./models";

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
  it("reads the run's models and current model, and switches it, over pi/rpc", async () => {
    const sendCommand = vi.fn(
      async ({
        params,
      }: {
        params: { command: { id: string; type: string } };
      }) => {
        const { id, type } = params.command;
        const data =
          type === "get_available_models"
            ? { models: [terra, opus] }
            : type === "get_state"
              ? { model: terra }
              : undefined;
        return {
          success: true,
          result: { id, type: "response", command: type, success: true, data },
        };
      },
    );
    const control = piControl(sendCommand as never, "t1", "r1");

    expect(await control.models()).toEqual({
      available: [terra, opus],
      current: terra,
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

  it("stops the agent's current turn", async () => {
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
        },
      }),
    );

    await piControl(sendCommand as never, "t1", "r1").abort();

    expect(sendCommand.mock.calls[0][0]).toMatchObject({
      method: "pi/rpc",
      params: { command: { type: "abort" } },
    });
  });
});
