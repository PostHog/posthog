import { mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parseCliArgs } from "./args";

// argv passed to parseCliArgs mirrors process.argv: [node, script, ...args].
function argv(...args: string[]): string[] {
  return ["/usr/bin/node", "/path/to/posthog-code-cli", ...args];
}

describe("parseCliArgs", () => {
  describe("defaults", () => {
    it("returns default options when no flags or prompt are given", () => {
      const result = parseCliArgs(argv());

      expect("error" in result).toBe(false);
      if ("error" in result) return;
      expect(result.prompt).toBeUndefined();
      expect(result.cwd).toBe(realpathSync(process.cwd()));
      expect(result.permissionMode).toBe("auto");
      expect(result.output).toBe("text");
      expect(result.debug).toBe(false);
    });
  });

  it("parses the prompt positional", () => {
    const result = parseCliArgs(argv("Fix the failing test"));

    expect("error" in result).toBe(false);
    if ("error" in result) return;
    expect(result.prompt).toBe("Fix the failing test");
  });

  describe("individual flags", () => {
    it("parses --cwd to the realpath of a valid directory", () => {
      const tmp = mkdtempSync(join(tmpdir(), "cli-args-test-"));
      const result = parseCliArgs(argv("--cwd", tmp));

      expect("error" in result).toBe(false);
      if ("error" in result) return;
      expect(result.cwd).toBe(realpathSync(tmp));
    });

    it("parses --permission-mode bypassPermissions", () => {
      const result = parseCliArgs(
        argv("--permission-mode", "bypassPermissions"),
      );

      expect("error" in result).toBe(false);
      if ("error" in result) return;
      expect(result.permissionMode).toBe("bypassPermissions");
    });

    it("parses a valid --model id", () => {
      const result = parseCliArgs(argv("--model", "claude-opus-4"));

      expect("error" in result).toBe(false);
      if ("error" in result) return;
      expect(result.model).toBe("claude-opus-4");
    });

    it("parses --system-prompt as-is", () => {
      const result = parseCliArgs(
        argv("--system-prompt", "Respond only in haiku"),
      );

      expect("error" in result).toBe(false);
      if ("error" in result) return;
      expect(result.systemPrompt).toBe("Respond only in haiku");
    });

    it("parses --output json", () => {
      const result = parseCliArgs(argv("--output", "json"));

      expect("error" in result).toBe(false);
      if ("error" in result) return;
      expect(result.output).toBe("json");
    });

    it("parses --debug as true when present", () => {
      const result = parseCliArgs(argv("--debug"));

      expect("error" in result).toBe(false);
      if ("error" in result) return;
      expect(result.debug).toBe(true);
    });
  });

  describe("invalid --permission-mode values", () => {
    it.each(["default", "plan", "acceptEdits", "yolo"])(
      "rejects %j with an error result",
      (mode) => {
        const result = parseCliArgs(argv("--permission-mode", mode));

        expect("error" in result).toBe(true);
        if (!("error" in result)) return;
        expect(typeof result.error).toBe("string");
        expect(result.error.length).toBeGreaterThan(0);
      },
    );
  });

  describe("invalid --model prefixes", () => {
    it.each(["gpt-4", "llama-3"])(
      "rejects %j since it does not start with claude-",
      (model) => {
        const result = parseCliArgs(argv("--model", model));

        expect("error" in result).toBe(true);
        if (!("error" in result)) return;
        expect(typeof result.error).toBe("string");
        expect(result.error.length).toBeGreaterThan(0);
      },
    );
  });

  it("rejects an invalid --output value", () => {
    const result = parseCliArgs(argv("--output", "yaml"));

    expect("error" in result).toBe(true);
    if (!("error" in result)) return;
    expect(typeof result.error).toBe("string");
    expect(result.error.length).toBeGreaterThan(0);
  });

  it("rejects a --cwd path that does not exist", () => {
    const bogusPath = join(tmpdir(), "definitely-does-not-exist-cli-args-test");
    const result = parseCliArgs(argv("--cwd", bogusPath));

    expect("error" in result).toBe(true);
    if (!("error" in result)) return;
    expect(typeof result.error).toBe("string");
    expect(result.error.length).toBeGreaterThan(0);
  });

  it("accepts a --cwd path pointing to a real directory", () => {
    const tmp = mkdtempSync(join(tmpdir(), "cli-args-test-"));
    const result = parseCliArgs(argv("--cwd", tmp));

    expect("error" in result).toBe(false);
    if ("error" in result) return;
    expect(result.cwd).toBe(realpathSync(tmp));
  });
});
