import { describe, expect, it } from "vitest";
import { applyOp, foldOps, fragmentsEqual } from "./ops";
import {
  emptySketchpadSnapshot,
  type SketchpadOp,
  type SketchpadSnapshot,
  sketchpadFragmentPatchSchema,
  sketchpadFragmentSchema,
} from "./schemas";

describe("foldOps", () => {
  it.each(["none", "first", "last", "multiple"])(
    "matches sequential replay with %s restores",
    (restores) => {
      const initial: SketchpadSnapshot = {
        ...emptySketchpadSnapshot(),
        state: { initial: true },
      };
      const edits: SketchpadOp[] = [
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
            surface: "card",
            hidden: false,
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
      const restore: SketchpadOp = {
        type: "restore",
        toSeq: 1,
        snapshot: { ...emptySketchpadSnapshot(), state: { restored: true } },
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
  it.each([
    { current: "old", initialValue: "different", accepted: false },
    {
      current: { label: "old" },
      initialValue: { label: "old" },
      accepted: false,
    },
    { current: { label: "old" }, accepted: false },
    { current: null, initialValue: "old", accepted: false },
    { current: "old", initialValue: "old", accepted: true },
    { current: null, accepted: true },
    {
      current: [{ a: 1, b: 2 }],
      initialValue: [{ b: 2, a: 1 }],
      accepted: true,
    },
  ])(
    "matches server field initialization for %j",
    ({ current, accepted, ...guard }) => {
      const snapshot = {
        ...emptySketchpadSnapshot(),
        state: { note: current },
      };
      const next = applyOp(snapshot, {
        type: "edit_field",
        key: "note",
        kind: "text",
        insert: [{ id: "first", k: "a0", v: "A" }],
        ...guard,
      });
      if (accepted) {
        expect(next.state.note).toEqual({
          __field: "text",
          entries: { first: { k: "a0", v: "A" } },
          removed: [],
        });
      } else {
        expect(next).toBe(snapshot);
      }
    },
  );

  it("defaults new fragments without filling in a partial update", () => {
    const fragment = sketchpadFragmentSchema.parse({
      id: "note",
      x: 0,
      y: 0,
      w: 360,
      h: 240,
      code: "null",
    });
    expect(fragment).toMatchObject({
      z: 0,
      codeVersion: 1,
      surface: "card",
      hidden: false,
    });
    const patch = sketchpadFragmentPatchSchema.parse({ x: 40 });
    expect(patch).toEqual({ x: 40 });
    expect(fragmentsEqual(fragment, { ...fragment, hidden: true })).toBe(false);
    expect(fragmentsEqual(fragment, { ...fragment, surface: "plain" })).toBe(
      false,
    );
  });
});
