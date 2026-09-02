import { describe, expect, it } from "vitest";
import { base64ToText } from "./base64";

const encode = (text: string): string =>
  Buffer.from(text, "utf-8").toString("base64");

describe("base64ToText", () => {
  it.each([
    ["ascii", "Deploy blocks on a stale lockfile"],
    ["multi-byte utf-8", "café — déjà vu 🚀 日本語"],
    ["multi-line", "first line\nsecond line\n"],
    ["empty", ""],
  ])("round-trips %s content", (_name, text) => {
    expect(base64ToText(encode(text))).toBe(text);
  });
});
