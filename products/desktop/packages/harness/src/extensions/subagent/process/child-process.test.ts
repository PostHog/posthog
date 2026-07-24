import { describe, expect, it } from "vitest";
import { spawnChildProcess } from "./child-process";

describe("spawnChildProcess", () => {
  it("line-buffers stdout and propagates the exit code", async () => {
    const lines: string[] = [];
    const handle = spawnChildProcess({
      command: process.execPath,
      args: ["-e", "process.stdout.write('a\\nb\\n'); process.exitCode = 3;"],
      onStdoutLine: (line) => lines.push(line),
    });

    const code = await handle.exited;
    expect(code).toBe(3);
    expect(lines).toEqual(["a", "b"]);
  });

  it("flushes a trailing unterminated line on exit", async () => {
    const lines: string[] = [];
    const handle = spawnChildProcess({
      command: process.execPath,
      args: ["-e", "process.stdout.write('no-newline')"],
      onStdoutLine: (line) => lines.push(line),
    });

    await handle.exited;
    expect(lines).toEqual(["no-newline"]);
  });

  it("captures stderr chunks", async () => {
    let stderr = "";
    const handle = spawnChildProcess({
      command: process.execPath,
      args: ["-e", "process.stderr.write('oops')"],
      onStderrChunk: (chunk) => {
        stderr += chunk;
      },
    });

    await handle.exited;
    expect(stderr).toBe("oops");
  });

  it("kill() terminates a long-running process and is idempotent", async () => {
    const handle = spawnChildProcess({
      command: process.execPath,
      args: ["-e", "setTimeout(() => {}, 60_000)"],
    });

    handle.kill();
    handle.kill(); // must not throw when called again

    const code = await handle.exited;
    expect(code).not.toBe(0);
  });

  it("resolves 1 instead of throwing when the command doesn't exist", async () => {
    const handle = spawnChildProcess({
      command: "posthog-subagent-definitely-not-a-real-binary",
      args: [],
    });
    const code = await handle.exited;
    expect(code).toBe(1);
  });

  it("resolves 1 instead of throwing when spawn() itself throws synchronously (e.g. an invalid cwd type)", async () => {
    let handle: ReturnType<typeof spawnChildProcess> | undefined;
    expect(() => {
      handle = spawnChildProcess({
        command: process.execPath,
        args: ["-e", "1"],
        // biome-ignore lint/suspicious/noExplicitAny: intentionally invalid to trigger spawn()'s synchronous validation throw
        cwd: 123 as any,
      });
    }).not.toThrow();

    const code = await handle?.exited;
    expect(code).toBe(1);
    expect(() => handle?.kill()).not.toThrow();
  });
});
