import { describe, expect, it } from "vitest";
import { applyOp, foldOps } from "./ops";
import {
  type CanvasV2Op,
  type CanvasV2Snapshot,
  emptyCanvasV2Snapshot,
} from "./schemas";

describe("foldOps", () => {
  it.each(["none", "first", "last", "multiple"])(
    "matches sequential replay with %s restores",
    (restores) => {
      const initial: CanvasV2Snapshot = {
        ...emptyCanvasV2Snapshot(),
        state: { initial: true },
      };
      const edits: CanvasV2Op[] = [
        {
          type: "add_fragment",
          fragment: {
            id: "note",
            x: 0,
            y: 0,
            w: 360,
            h: 240,
            z: 0,
            code: "null",
            codeVersion: 1,
          },
        },
        { type: "update_fragment", id: "note", patch: { x: 40 } },
        { type: "bring_to_front", id: "note" },
        { type: "set_state", key: "title", value: "Test" },
        {
          type: "edit_field",
          key: "text",
          kind: "text",
          insert: [{ id: "a", k: "a", v: "A" }],
        },
        { type: "remove_fragment", id: "note" },
      ];
      const restore: CanvasV2Op = {
        type: "restore",
        toSeq: 1,
        snapshot: { ...emptyCanvasV2Snapshot(), state: { restored: true } },
      };
      const ops =
        restores === "none"
          ? edits
          : restores === "first"
            ? [restore, ...edits]
            : restores === "last"
              ? [...edits, restore]
              : [
                  restore,
                  ...edits,
                  { ...restore, snapshot: initial },
                  ...edits.slice(3),
                ];
      const expected = ops.reduce(applyOp, initial);

      expect(
        foldOps(
          initial,
          ops.map((op) => ({ op })),
        ),
      ).toEqual(expected);
      expect(initial.state).toEqual({ initial: true });
      expect(restore.snapshot.state).toEqual({ restored: true });
      expect(foldOps(initial, [])).toBe(initial);
    },
  );
});
