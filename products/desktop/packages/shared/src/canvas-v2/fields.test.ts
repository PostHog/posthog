import { describe, expect, it } from "vitest";
import {
  type CanvasV2Field,
  diffTextToOps,
  emptyField,
  isField,
  keyBetween,
  materializeText,
  newEntryId,
} from "./fields";
import { applyOp } from "./ops";
import { type CanvasV2Snapshot, emptyCanvasV2Snapshot } from "./schemas";

const ALPHABET =
  "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

function fieldOf(text: string, key: string): CanvasV2Field {
  let snapshot = emptyCanvasV2Snapshot();
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
  field: CanvasV2Field,
  next: string,
  clientId: string,
  key = "note",
): CanvasV2Field {
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
  let snapshot: CanvasV2Snapshot = {
    ...emptyCanvasV2Snapshot(),
    state: { [key]: field },
  };
  for (const op of result.ops) snapshot = applyOp(snapshot, op);
  const value = snapshot.state[key];
  if (!isField(value)) throw new Error("the edit did not keep the field");
  return value;
}

describe("canvas v2 fields", () => {
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
      let snapshot: CanvasV2Snapshot = {
        ...emptyCanvasV2Snapshot(),
        state: { note: value },
      };
      for (const op of ops) snapshot = applyOp(snapshot, op);
      const next = snapshot.state.note;
      if (!isField(next)) throw new Error("the edit did not keep the field");
      expect(materializeText(next).text).toBe("XB");
    },
  );

  it("keeps inserts from sessions with the same short prefix", () => {
    let snapshot = emptyCanvasV2Snapshot();
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
    expect(materializeText(snapshot.state.note as CanvasV2Field).text).toBe(
      "AB",
    );
  });
  it("puts a key between two neighbors", () => {
    const a = keyBetween(null, null);
    const b = keyBetween(a, null);
    const middle = keyBetween(a, b);
    expect(a < middle).toBe(true);
    expect(middle < b).toBe(true);
  });

  it("puts a key after one neighbor and before one neighbor", () => {
    const a = keyBetween(null, null);
    expect(keyBetween(a, null) > a).toBe(true);
    expect(keyBetween(null, a) < a).toBe(true);
  });

  it("keeps a long run of inserts in order at the same gap", () => {
    const left = keyBetween(null, null);
    const right = keyBetween(left, null);
    const keys: string[] = [];
    let previous = left;
    for (let i = 0; i < 300; i++) {
      previous = keyBetween(previous, right);
      keys.push(previous);
    }
    const sorted = [...keys].sort();
    expect(keys).toEqual(sorted);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys[keys.length - 1] < right).toBe(true);
  });

  it("keeps a long run of appends short and in order", () => {
    const keys: string[] = [];
    let previous: string | null = null;
    for (let i = 0; i < 5000; i++) {
      previous = keyBetween(previous, null);
      keys.push(previous);
    }
    expect(keys).toEqual([...keys].sort());
    expect(Math.max(...keys.map((key) => key.length))).toBeLessThanOrEqual(64);
  });

  it("uses no character outside the alphabet", () => {
    const keys = [keyBetween(null, null)];
    for (let i = 0; i < 200; i++) {
      const last = keys[keys.length - 1];
      keys.push(keyBetween(last, null), keyBetween(null, last));
    }
    for (const key of keys) {
      for (const character of key) {
        expect(ALPHABET.includes(character)).toBe(true);
      }
    }
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
    let snapshot: CanvasV2Snapshot = {
      ...emptyCanvasV2Snapshot(),
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
      { ...emptyCanvasV2Snapshot(), state: { note: emptied } },
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
