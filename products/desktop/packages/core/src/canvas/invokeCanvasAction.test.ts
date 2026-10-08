import { describe, expect, it, vi } from "vitest";
import { invokeCanvasAction } from "./invokeCanvasAction";

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
});
