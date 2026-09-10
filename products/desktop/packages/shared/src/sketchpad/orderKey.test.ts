import { describe, expect, it } from "vitest";
import { keyBetween } from "./orderKey";

const ALPHABET =
  "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

describe("order keys", () => {
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
    expect(left < keys[0]).toBe(true);
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
});
