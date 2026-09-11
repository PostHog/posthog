import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import {
  matchesExcludePatterns,
  parseExcludePatterns,
} from "./exclude-patterns";

function matches(content: string, entry: string): boolean {
  return matchesExcludePatterns(entry, parseExcludePatterns(content));
}

describe("parseExcludePatterns", () => {
  it.each([
    ["empty content", ""],
    ["only comments", "# a comment\n# another"],
    ["only blank lines", "\n\n  \n"],
    ["a lone negation marker", "!"],
    ["a lone slash", "/"],
  ])("produces no patterns from %s", (_label, content) => {
    expect(parseExcludePatterns(content)).toEqual([]);
  });

  it.each([String.raw`[\]x`, String.raw`[a\]]`])(
    "skips a syntax-invalid ambiguous class: %s",
    (pattern) => {
      const patterns = parseExcludePatterns(`${pattern}\n.env`);
      expect(patterns).toHaveLength(1);
      expect(matchesExcludePatterns(".env", patterns)).toBe(true);
    },
  );

  it.each([String.raw`[\]a[bc]`, "[]a]", "[]|a]"])(
    "surfaces accepted ambiguous class syntax to the caller's Git fallback: %s",
    (pattern) => {
      expect(() => parseExcludePatterns(pattern)).toThrow(
        "Ambiguous exclude character class",
      );
    },
  );
});

describe("matchesExcludePatterns", () => {
  it.each([
    ["basename pattern matches at root", ".env", ".env", true],
    ["basename pattern matches nested", ".env", "config/sub/.env", true],
    [
      "basename pattern does not match other names",
      ".env",
      ".env.local",
      false,
    ],
    ["comment lines never match", "# .env", ".env", false],
    ["star glob within a segment", "*.local", ".env.local", true],
    [
      "star glob matches a nested file via the non-anchored prefix",
      "*.local",
      "a/b.local",
      true,
    ],
    ["star does not span slashes", "a*b", "a/b", false],
    ["question mark matches one char", ".env?", ".envX", true],
    ["question mark does not match slash", ".env?", ".env/", false],
    ["anchored pattern matches from root only", "/build", "build", true],
    ["anchored pattern rejects nested path", "/build", "sub/build", false],
    [
      "middle-slash pattern anchors to root",
      "config/secrets",
      "config/secrets",
      true,
    ],
    [
      "middle-slash pattern rejects nested",
      "config/secrets",
      "app/config/secrets",
      false,
    ],
    ["dir-only pattern matches directory entry", ".flox/", ".flox/", true],
    ["dir-only pattern rejects plain file", ".flox/", ".flox", false],
    ["dir pattern matches files beneath it", ".flox", ".flox/cache/data", true],
    [
      "dir-only pattern matches files beneath it",
      ".flox/",
      ".flox/cache/data",
      true,
    ],
    ["double star prefix matches any depth", "**/logs", "a/b/logs", true],
    ["double star suffix matches contents", "logs/**", "logs/a/b.txt", true],
    [
      "double star suffix does not match the dir itself",
      "logs/**",
      "logs",
      false,
    ],
    ["middle double star spans directories", "a/**/b", "a/x/y/b", true],
    ["middle double star matches zero directories", "a/**/b", "a/b", true],
    ["character class matches", ".env.[ab]", ".env.a", true],
    ["negated character class rejects", ".env.[!ab]", ".env.a", false],
    [
      "negation un-matches an earlier pattern",
      ".env*\n!.env.example",
      ".env.example",
      false,
    ],
    [
      "negation only affects matching entries",
      ".env*\n!.env.example",
      ".env",
      true,
    ],
    ["later pattern wins over earlier negation", "!.env\n.env", ".env", true],
    ["escaped bang matches literal bang", "\\!important", "!important", true],
    ["escaped hash matches literal hash", "\\#file", "#file", true],
    ["trailing spaces are trimmed", ".env   ", ".env", true],
    ["CRLF line endings do not defeat matching", ".env\r\n", ".env", true],
    ["escaped trailing space survives cleanup", "file\\   ", "file ", true],
    ["only one final CR is removed", "file\r\r", "file\r", true],
    ["trailing tabs remain literal", "file\t", "file\t", true],
    ["a trailing backslash remains literal", "file\\", "file\\", true],
    ["question marks consume UTF-16 units", "??", "😀", true],
    ["one question mark rejects a surrogate pair", "?", "😀", false],
    ["single star consumes newlines", "/a*b", "a\nb", true],
    ["double star rejects newlines", "/a**b", "a\nb", false],
    ["basename prefix rejects newlines", "b", "a\n/b", false],
    ["directory glob rejects newlines", "a/**/b", "a/x\n/b", false],
    ["literal ending rejects a final newline", "a", "a\n", false],
    ["parent match stops before a newline", "a", "a/x\n", true],
    ["character class permits slash", "a[/]b", "a/b", true],
    ["negated empty class matches newline", "[^]", "\n", true],
    ["bang empty class matches newline", "[!]", "\n", true],
    ["native character class escape", String.raw`[\d]`, "1", true],
    ["native character class hex escape", String.raw`[\x61]`, "a", true],
    ["native character class identity escape", String.raw`[\q]`, "q", true],
    ["class containing escaped backslash", String.raw`[\\]`, "\\", true],
    ["invalid class range skips its line", "[z-a]\n.env", ".env", true],
    ["unterminated bracket remains literal", "[[", "[[", true],
    [
      "consecutive double-star segments collapse",
      "**/**/logs",
      "a/b/logs",
      true,
    ],
  ])("%s", (_label, content, entry, expected) => {
    expect(matches(content, entry)).toBe(expected);
  });

  it("skips a malformed pattern line instead of dropping the whole file", () => {
    // An unterminated char class on one line must not throw out the valid ones.
    const patterns = parseExcludePatterns(".env\n[\n.envrc");
    expect(matchesExcludePatterns(".env", patterns)).toBe(true);
    expect(matchesExcludePatterns(".envrc", patterns)).toBe(true);
  });

  it.each([
    ["separated stars", `${"*a".repeat(12)}b`, "a".repeat(100)],
    ["consecutive double stars", `${"**/".repeat(30)}NOMATCH`, "a/".repeat(24)],
    ["trailing-space preprocessing", `${" ".repeat(64000)}!`, "a"],
  ])("bounds %s in a killable child", (_label, content, entry) => {
    const moduleUrl = new URL("./exclude-patterns.ts", import.meta.url).href;
    const result = spawnSync(
      process.execPath,
      [
        "--input-type=module",
        "-e",
        `
      import { parseExcludePatterns, matchesExcludePatterns } from ${JSON.stringify(moduleUrl)};
      process.stdout.write(JSON.stringify(matchesExcludePatterns(${JSON.stringify(entry)}, parseExcludePatterns(${JSON.stringify(content)}))));
    `,
      ],
      { encoding: "utf8", timeout: 1500, killSignal: "SIGKILL" },
    );
    expect(result.error).toBeUndefined();
    expect(result.status, result.stderr).toBe(0);
    expect(result.stdout).toBe("false");
  });

  it("never matches entries only reachable through unrelated names", () => {
    expect(matches(".env", "node_modules/")).toBe(false);
    expect(matches(".env", "dist/")).toBe(false);
  });
});
