import { describe, expect, it } from "vitest";
import { diffTextToOps } from "./diffText";
import {
  emptyField,
  isField,
  materializeText,
  newEntryId,
  type SketchpadField,
} from "./fields";
import { applyOp } from "./ops";
import { emptySketchpadSnapshot, type SketchpadSnapshot } from "./schemas";

function fieldOf(text: string, key: string): SketchpadField {
  let snapshot = emptySketchpadSnapshot();
  const result = diffTextToOps({
    base: "",
    baseIds: [],
    next: text,
    field: emptyField("text"),
    key,
    clientId: "seed00",
    counterStart: 0,
  });
  for (const op of result.ops) snapshot = applyOp(snapshot, op);
  const value = snapshot.state[key];
  if (!isField(value)) throw new Error("the seed did not make a field");
  return value;
}

function typeInto(
  field: SketchpadField,
  next: string,
  clientId: string,
  key = "note",
): SketchpadField {
  const current = materializeText(field);
  const result = diffTextToOps({
    base: current.text,
    baseIds: current.ids,
    next,
    field,
    key,
    clientId,
    counterStart: 100,
  });
  let snapshot: SketchpadSnapshot = {
    ...emptySketchpadSnapshot(),
    state: { [key]: field },
  };
  for (const op of result.ops) snapshot = applyOp(snapshot, op);
  const value = snapshot.state[key];
  if (!isField(value)) throw new Error("the edit did not keep the field");
  return value;
}

describe("sketchpad fields", () => {
  it.each([null, { k: null, v: "A" }, { k: 1, v: "A" }])(
    "keeps valid text and edits when a stored entry is %j",
    (bad) => {
      const value: unknown = {
        __field: "text",
        entries: { bad, good: { k: "a1", v: "B" } },
        removed: [],
      };
      if (!isField(value)) throw new Error("the field container is valid");
      expect(materializeText(value)).toEqual({ text: "B", ids: ["good"] });
      const { ops } = diffTextToOps({
        base: "AB",
        baseIds: ["bad", "good"],
        next: "AXB",
        field: value,
        key: "note",
        clientId: "test",
        counterStart: 0,
      });
      let snapshot: SketchpadSnapshot = {
        ...emptySketchpadSnapshot(),
        state: { note: value },
      };
      for (const op of ops) snapshot = applyOp(snapshot, op);
      const next = snapshot.state.note;
      if (!isField(next)) throw new Error("the edit did not keep the field");
      expect(materializeText(next).text).toBe("XB");
    },
  );

  it("keeps inserts from sessions with the same short prefix", () => {
    let snapshot = emptySketchpadSnapshot();
    for (const [clientId, value] of [
      ["abcdef11111111111111111111111111", "A"],
      ["abcdef22222222222222222222222222", "B"],
    ]) {
      snapshot = applyOp(snapshot, {
        type: "edit_field",
        key: "note",
        kind: "text",
        insert: [{ id: newEntryId(clientId, 0), k: "a0", v: value }],
      });
    }
    expect(materializeText(snapshot.state.note as SketchpadField).text).toBe(
      "AB",
    );
  });

  it.each([
    ["a keystroke", "hello", "hello!"],
    ["a paste", "hello", "hello, world and more text"],
    ["a backspace", "hello", "hell"],
    ["a replaced selection", "hello world", "hello there"],
    ["an emptied field", "hello", ""],
    ["an insert at the start", "world", "hello world"],
  ])("applies %s", (_name, base, next) => {
    const field = fieldOf(base, "note");
    const after = typeInto(field, next, "alice0");
    expect(materializeText(after).text).toBe(next);
  });

  it("keeps what somebody else typed at the same time", () => {
    const start = fieldOf("hello", "note");
    const remote = typeInto(start, "hello there", "bob000");
    const mine = materializeText(start);

    const result = diffTextToOps({
      base: mine.text,
      baseIds: mine.ids,
      next: "hello!",
      field: remote,
      key: "note",
      clientId: "alice0",
      counterStart: 0,
    });
    let snapshot: SketchpadSnapshot = {
      ...emptySketchpadSnapshot(),
      state: { note: remote },
    };
    for (const op of result.ops) snapshot = applyOp(snapshot, op);
    const value = snapshot.state.note;
    if (!isField(value)) throw new Error("the edit did not keep the field");

    const text = materializeText(value).text;
    expect(text).toContain("there");
    expect(text).toContain("!");
    expect(text.startsWith("hello")).toBe(true);
  });

  it("removes only the ids of the characters that changed", () => {
    const field = fieldOf("hello", "note");
    const before = materializeText(field);
    const result = diffTextToOps({
      base: before.text,
      baseIds: before.ids,
      next: "heLLo",
      field,
      key: "note",
      clientId: "alice0",
      counterStart: 0,
    });
    const removed = result.ops.flatMap((op) =>
      op.type === "edit_field" ? (op.remove ?? []) : [],
    );
    expect(removed).toEqual([before.ids[2], before.ids[3]]);
    expect(result.counterEnd).toBe(2);
  });

  it("makes no op when the text does not change", () => {
    const field = fieldOf("hello", "note");
    const current = materializeText(field);
    const result = diffTextToOps({
      base: current.text,
      baseIds: current.ids,
      next: "hello",
      field,
      key: "note",
      clientId: "alice0",
      counterStart: 7,
    });
    expect(result.ops).toEqual([]);
    expect(result.counterEnd).toBe(7);
  });

  it("never brings a removed id back", () => {
    const field = fieldOf("hi", "note");
    const ids = materializeText(field).ids;
    const emptied = typeInto(field, "", "alice0");
    const late = applyOp(
      { ...emptySketchpadSnapshot(), state: { note: emptied } },
      {
        type: "edit_field",
        key: "note",
        kind: "text",
        insert: [{ id: ids[0], k: "a0VV", v: "h" }],
      },
    );
    const value = late.state.note;
    if (!isField(value)) throw new Error("the edit did not keep the field");
    expect(materializeText(value).text).toBe("");
  });
});
