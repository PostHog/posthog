import { mkdtempSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { type CliOptions, type ParseResult, parseCliArgs } from "./args";

// argv passed to parseCliArgs mirrors process.argv: [node, script, ...args].
function argv(...args: string[]): string[] {
  return ["/usr/bin/node", "/path/to/posthog-code-cli", ...args];
}

// Assert and narrow in one step, so an unexpected parse failure reports the
// message that caused it rather than "expected true to be false".
function expectOptions(result: ParseResult): CliOptions {
  if (result.kind !== "options") {
    throw new Error(
      `expected parsed options, got ${result.kind}: ${JSON.stringify(result)}`,
    );
  }
  return result.options;
}

function expectError(result: ParseResult): string {
  if (result.kind !== "error") {
    throw new Error(
      `expected a parse error, got ${result.kind}: ${JSON.stringify(result)}`,
    );
  }
  return result.message;
}

describe("parseCliArgs", () => {
  describe("defaults", () => {
    it("returns default options when no flags or prompt are given", () => {
      const options = expectOptions(parseCliArgs(argv()));

      expect(options.prompt).toBeUndefined();
      expect(options.cwd).toBe(realpathSync(process.cwd()));
      expect(options.permissionMode).toBe("auto");
      expect(options.output).toBe("text");
      expect(options.debug).toBe(false);
    });
  });

  it("parses the prompt positional", () => {
    const options = expectOptions(parseCliArgs(argv("Fix the failing test")));

    expect(options.prompt).toBe("Fix the failing test");
  });

  describe("individual flags", () => {
    it("parses --cwd to the realpath of a valid directory", () => {
      const tmp = mkdtempSync(join(tmpdir(), "cli-args-test-"));
      const options = expectOptions(parseCliArgs(argv("--cwd", tmp)));

      expect(options.cwd).toBe(realpathSync(tmp));
    });

    it("parses --permission-mode bypassPermissions", () => {
      const options = expectOptions(
        parseCliArgs(argv("--permission-mode", "bypassPermissions")),
      );

      expect(options.permissionMode).toBe("bypassPermissions");
    });

    it("parses a valid --model id", () => {
      const options = expectOptions(
        parseCliArgs(argv("--model", "claude-opus-4")),
      );

      expect(options.model).toBe("claude-opus-4");
    });

    it("parses --system-prompt as-is", () => {
      const options = expectOptions(
        parseCliArgs(argv("--system-prompt", "Respond only in haiku")),
      );

      expect(options.systemPrompt).toBe("Respond only in haiku");
    });

    it("parses --output json", () => {
      const options = expectOptions(parseCliArgs(argv("--output", "json")));

      expect(options.output).toBe("json");
    });

    it("parses --debug as true when present", () => {
      const options = expectOptions(parseCliArgs(argv("--debug")));

      expect(options.debug).toBe(true);
    });
  });

  describe("invalid --permission-mode values", () => {
    it.each(["default", "plan", "acceptEdits", "yolo"])(
      "rejects %j and names the allowed modes",
      (mode) => {
        const message = expectError(
          parseCliArgs(argv("--permission-mode", mode)),
        );

        // Message content, not just non-emptiness: an "unknown option" error
        // would otherwise pass as if the value had been rejected.
        expect(message).toMatch(/auto/);
        expect(message).toMatch(/bypassPermissions/);
      },
    );
  });

  describe("invalid --model prefixes", () => {
    it.each(["gpt-4", "llama-3"])(
      "rejects %j since it does not start with claude-",
      (model) => {
        expect(expectError(parseCliArgs(argv("--model", model)))).toMatch(
          /claude-/,
        );
      },
    );
  });

  it("rejects an invalid --output value", () => {
    const message = expectError(parseCliArgs(argv("--output", "yaml")));

    expect(message).toMatch(/text/);
    expect(message).toMatch(/json/);
  });

  it("rejects a --cwd path that does not exist", () => {
    const bogusPath = join(tmpdir(), "definitely-does-not-exist-cli-args-test");

    expect(expectError(parseCliArgs(argv("--cwd", bogusPath)))).toMatch(
      /No such directory/,
    );
  });

  it("rejects a --cwd path pointing to a file rather than a directory", () => {
    const file = join(mkdtempSync(join(tmpdir(), "cli-args-test-")), "f.txt");
    writeFileSync(file, "x");

    expect(expectError(parseCliArgs(argv("--cwd", file)))).toMatch(
      /Not a directory/,
    );
  });

  it("accepts a --cwd path pointing to a real directory", () => {
    const tmp = mkdtempSync(join(tmpdir(), "cli-args-test-"));
    const options = expectOptions(parseCliArgs(argv("--cwd", tmp)));

    expect(options.cwd).toBe(realpathSync(tmp));
  });

  // Commander writes help to stdout itself, so the result carries no message
  // and exit 0. Inverting this would break any script that probes usage.
  it("maps --help to a silent success", () => {
    expect(parseCliArgs(argv("--help"))).toEqual({ kind: "exit", exitCode: 0 });
  });
});
