import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import { installStdioShutdownGuards } from "./stdio-lifecycle";

describe("installStdioShutdownGuards", () => {
  type FakeProcess = EventEmitter & {
    stdout: EventEmitter;
    stderr: EventEmitter;
    stdin: EventEmitter;
    exit: ReturnType<typeof vi.fn>;
  };

  function fakeProcess(): FakeProcess {
    const proc = new EventEmitter() as FakeProcess;
    proc.stdout = new EventEmitter();
    proc.stderr = new EventEmitter();
    proc.stdin = new EventEmitter();
    proc.exit = vi.fn();
    return proc;
  }

  function install(proc: FakeProcess): void {
    installStdioShutdownGuards(proc as unknown as NodeJS.Process);
  }

  function errWithCode(code: string): NodeJS.ErrnoException {
    const err: NodeJS.ErrnoException = new Error(`write ${code}`);
    err.code = code;
    return err;
  }

  it.each(["stdout", "stderr"] as const)(
    "exits with 0 when a %s write hits a closed pipe",
    (stream) => {
      const proc = fakeProcess();
      install(proc);

      proc[stream].emit("error", errWithCode("EPIPE"));

      expect(proc.exit).toHaveBeenCalledWith(0);
    },
  );

  it.each(["end", "close"] as const)(
    "exits with 0 when stdin emits %s",
    (event) => {
      const proc = fakeProcess();
      install(proc);

      proc.stdin.emit(event);

      expect(proc.exit).toHaveBeenCalledWith(0);
    },
  );

  it.each(["uncaughtException", "unhandledRejection"] as const)(
    "exits with 0 on a closed-pipe %s",
    (event) => {
      const proc = fakeProcess();
      install(proc);

      proc.emit(event, errWithCode("EPIPE"));

      expect(proc.exit).toHaveBeenCalledWith(0);
    },
  );

  it("keeps crashing on a write failure that is not a closed pipe", () => {
    const proc = fakeProcess();
    install(proc);

    expect(() => proc.stdout.emit("error", errWithCode("ENOSPC"))).toThrow(
      "write ENOSPC",
    );
    expect(proc.exit).not.toHaveBeenCalled();
  });

  it("keeps crashing on an uncaught exception that is not a closed pipe", () => {
    const proc = fakeProcess();
    install(proc);

    expect(() =>
      proc.emit("uncaughtException", new Error("tool blew up")),
    ).toThrow("tool blew up");
    expect(proc.exit).not.toHaveBeenCalled();
  });
});
