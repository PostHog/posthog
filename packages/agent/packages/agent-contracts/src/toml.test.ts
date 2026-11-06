import { describe, expect, it } from "vitest";
import { tomlBasicString } from "./toml";

describe("tomlBasicString", () => {
  it.each([
    ["http://127.0.0.1:1/tok", '"http://127.0.0.1:1/tok"'],
    ['a"b\\c', '"a\\"b\\\\c"'],
    ["line\nbreak", '"line\\nbreak"'],
    ["x\r\ty", '"x\\r\\ty"'],
    ["nul\u0000del\u007f", '"nul\\u0000del\\u007f"'],
  ])("escapes %j", (raw, quoted) => {
    expect(tomlBasicString(raw)).toBe(quoted);
  });

  it("keeps an injected table header inside the string", () => {
    expect(tomlBasicString('x"\n[evil]\nk = "v')).not.toMatch(/\n/);
  });
});
