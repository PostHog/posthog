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

  it("matches a pathological consecutive-double-star pattern in bounded time", () => {
    // Regression for ReDoS: a run of `**/` used to compile to that many
    // overlapping backtracking groups, blowing up exponentially with path depth.
    const pattern = `${Array(30).fill("**").join("/")}/NOMATCH`;
    const patterns = parseExcludePatterns(pattern);
    const deepPath = `${Array.from({ length: 24 }, (_, i) => String.fromCharCode(97 + (i % 26))).join("/")}/`;
    const start = performance.now();
    expect(matchesExcludePatterns(deepPath, patterns)).toBe(false);
    expect(performance.now() - start).toBeLessThan(1000);
  });

  it("never matches entries only reachable through unrelated names", () => {
    expect(matches(".env", "node_modules/")).toBe(false);
    expect(matches(".env", "dist/")).toBe(false);
  });
});
