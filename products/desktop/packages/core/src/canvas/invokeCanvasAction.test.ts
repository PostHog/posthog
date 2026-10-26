import { describe, expect, it, vi } from "vitest";
import { invokeCanvasAction, invokeCanvasTool } from "./invokeCanvasAction";

const input = {
  id: "canvas-1",
  verb: "workflows.pause",
  payload: { workflow_ids: ["workflow-1"] },
};
const action = {
  verb: "workflows.pause",
  summary: "Disable workflows in this project so they stop running.",
  destructive: true,
};

describe("invokeCanvasAction", () => {
  it.each([true, false])(
    "requires host confirmation for a destructive action (allowed: %s)",
    async (allowed) => {
      const confirm = vi.fn().mockReturnValue(allowed);
      const invoke = vi
        .fn()
        .mockResolvedValue({ verb: action.verb, result: {} });
      const result = invokeCanvasAction(
        input,
        async () => [action],
        confirm,
        invoke,
      );
      if (allowed) {
        await expect(result).resolves.toEqual({
          verb: action.verb,
          result: {},
        });
        expect(invoke).toHaveBeenCalledWith(input);
      } else {
        await expect(result).rejects.toThrow("Canvas action canceled");
        expect(invoke).not.toHaveBeenCalled();
      }
      expect(confirm).toHaveBeenCalledWith(action);
    },
  );

  it("refuses an action absent from the server registry", async () => {
    const invoke = vi.fn();
    await expect(
      invokeCanvasAction(input, async () => [], vi.fn(), invoke),
    ).rejects.toThrow("Unknown canvas action");
    expect(invoke).not.toHaveBeenCalled();
  });

  it("does not ask for confirmation for a non-destructive action", async () => {
    const confirm = vi.fn();
    const invoke = vi.fn().mockResolvedValue({ verb: action.verb, result: {} });
    await invokeCanvasAction(
      input,
      async () => [{ ...action, destructive: false }],
      confirm,
      invoke,
    );
    expect(confirm).not.toHaveBeenCalled();
    expect(invoke).toHaveBeenCalledWith(input);
  });

  describe("invokeCanvasTool", () => {
    const writeTool = {
      name: "feature-flag-enable",
      summary: "Enable feature flag",
      read_only: false,
      destructive: false,
    };
    const readTool = {
      ...writeTool,
      name: "feature-flag-get-definition",
      read_only: true,
    };

    it.each([
      // A canvas must not change data from a load or render.
      [writeTool, false, true, "changes data"],
      [writeTool, true, false, "Canvas tool call canceled"],
      [writeTool, true, true, null],
      [readTool, false, false, null],
    ])(
      "runs %o from a gesture %s with approval %s",
      async (tool, fromGesture, allowed, error) => {
        const confirm = vi.fn().mockReturnValue(allowed);
        const invoke = vi
          .fn()
          .mockResolvedValue({ tool: tool.name, result: {} });
        const call = { id: "canvas-1", tool: tool.name, arguments: { id: 7 } };
        const result = invokeCanvasTool(
          call,
          fromGesture,
          async () => [writeTool, readTool],
          confirm,
          invoke,
        );
        if (error) {
          await expect(result).rejects.toThrow(error);
          expect(invoke).not.toHaveBeenCalled();
        } else {
          await expect(result).resolves.toEqual({
            tool: tool.name,
            result: {},
          });
          expect(invoke).toHaveBeenCalledWith(call);
        }
        if (confirm.mock.calls.length > 0) {
          expect(confirm).toHaveBeenCalledWith(tool, call.arguments);
        }
      },
    );
  });
});
