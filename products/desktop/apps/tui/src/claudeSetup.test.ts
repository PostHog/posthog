import type { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { chmodSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";
import { claudeOnPath, runClaudeSetupToken } from "./claudeSetup";

const TOKEN = `sk-ant-oat01-${"x".repeat(40)}`;

// A child that prints `output` and exits with `code`.
const fakeSpawn = (output: string, code: number): typeof spawn =>
  ((): unknown => {
    const child = Object.assign(new EventEmitter(), {
      stdout: new PassThrough(),
    });
    setImmediate(() => {
      child.stdout.end(output);
      child.emit("close", code);
    });
    return child;
  }) as unknown as typeof spawn;

describe("claudeSetup", () => {
  it.each([
    [
      "the token it prints, without its colours",
      `Opening your browser…\n\u001b[1m${TOKEN}\u001b[22m\nKeep it secret.\n`,
      0,
      TOKEN,
    ],
    ["no token", "Opening your browser…\n", 0, "printed no token"],
    ["a failure", "Not logged in\n", 1, "exited with 1"],
  ])("returns %s", async (_, output, code, expected) => {
    const mirrored = new PassThrough();
    let seen = "";
    mirrored.on("data", (chunk: Buffer) => {
      seen += chunk.toString("utf8");
    });
    const result = runClaudeSetupToken(fakeSpawn(output, code), mirrored);
    if (expected === TOKEN) await expect(result).resolves.toBe(TOKEN);
    else await expect(result).rejects.toThrow(expected);
    expect(seen).toBe(output);
  });

  it("finds claude on PATH only where it is executable", () => {
    const dir = mkdtempSync(join(tmpdir(), "claude-on-path-"));
    expect(claudeOnPath(dir)).toBe(false);
    writeFileSync(join(dir, "claude"), "#!/bin/sh\n");
    chmodSync(join(dir, "claude"), 0o755);
    expect(claudeOnPath(`/nowhere:${dir}`)).toBe(true);
  });
});
