import {
  applyOp,
  CANVAS_V2_FIELD_MAX_ENTRIES,
  type CanvasV2Field,
  emptyCanvasV2Snapshot,
  materializeList,
} from "@posthog/shared";
import { QueryClient } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import {
  type CanvasV2DataBridgeContext,
  handleCanvasV2DataRequest,
} from "./canvasV2DataBridge";

it.each(["remote edit", "restore"])(
  "keeps current field data after %s",
  async (change) => {
    let snapshot = emptyCanvasV2Snapshot();
    const ctx: CanvasV2DataBridgeContext = {
      boardId: change,
      queryClient: new QueryClient(),
      getSnapshot: () => snapshot,
      applyLocal: (ops) => {
        for (const op of ops) snapshot = applyOp(snapshot, op);
      },
      reportCaret: vi.fn(),
    };
    const edit = (payload: object) =>
      handleCanvasV2DataRequest(
        "stateEditList",
        { key: "items", ...payload },
        ctx,
      );
    await edit({ insert: [{ value: "initial" }] });
    const saved = snapshot;
    const field = snapshot.state.items as CanvasV2Field;
    const [id] = Object.keys(field.entries);
    if (change === "restore") {
      await edit({ remove: [id] });
      snapshot = applyOp(snapshot, {
        type: "restore",
        snapshot: saved,
        toSeq: 1,
      });
    } else {
      snapshot = applyOp(snapshot, {
        type: "edit_field",
        key: "items",
        kind: "list",
        insert: [{ id, k: field.entries[id].k, v: "remote" }],
      });
    }
    const answer = await edit({ insert: [{ afterId: id, value: "addition" }] });
    const items = materializeList(snapshot.state.items as CanvasV2Field);
    expect(items.map((item) => item.value)).toEqual([
      change === "restore" ? "initial" : "remote",
      "addition",
    ]);
    expect(answer).toEqual({ items });
  },
);

it.each(["a", "🙂"])(
  "rejects oversized text before writing: %s",
  async (character) => {
    const applyLocal = vi.fn();
    await expect(
      handleCanvasV2DataRequest(
        "stateEditText",
        {
          key: "note",
          base: "",
          baseIds: [],
          next: character.repeat(CANVAS_V2_FIELD_MAX_ENTRIES + 1),
        },
        {
          boardId: character,
          queryClient: new QueryClient(),
          getSnapshot: emptyCanvasV2Snapshot,
          applyLocal,
          reportCaret: vi.fn(),
        },
      ),
    ).rejects.toThrow();
    expect(applyLocal).not.toHaveBeenCalled();
  },
);
