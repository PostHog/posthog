/**
 * Shutdown guards for a spawned stdio MCP server.
 *
 * The parent process owns both pipes. When it goes away while a tool response is
 * in flight, the write fails with EPIPE and the read side ends. Both are normal
 * shutdown, so the child exits quietly instead of crashing and reporting a
 * production error. Any other failure keeps its current crash behaviour.
 */

const QUIET_EXIT_CODES = new Set(["EPIPE", "ERR_STREAM_DESTROYED"]);

function isClosedPipe(err: unknown): boolean {
  const code = (err as NodeJS.ErrnoException | undefined)?.code;
  return typeof code === "string" && QUIET_EXIT_CODES.has(code);
}

export function installStdioShutdownGuards(proc: NodeJS.Process): void {
  const exitQuietly = (): void => {
    proc.exit(0);
  };

  for (const stream of [proc.stdout, proc.stderr]) {
    stream.on("error", (err: unknown) => {
      if (isClosedPipe(err)) {
        exitQuietly();
        return;
      }
      throw err;
    });
  }

  proc.stdin.on("end", exitQuietly);
  proc.stdin.on("close", exitQuietly);

  const rethrowUnlessClosedPipe = (err: unknown): void => {
    if (isClosedPipe(err)) {
      exitQuietly();
      return;
    }
    proc.removeListener("uncaughtException", rethrowUnlessClosedPipe);
    proc.removeListener("unhandledRejection", rethrowUnlessClosedPipe);
    throw err;
  };

  proc.on("uncaughtException", rethrowUnlessClosedPipe);
  proc.on("unhandledRejection", rethrowUnlessClosedPipe);
}
