/**
 * Shutdown guards for a spawned stdio MCP server.
 *
 * The parent process owns both pipes. When it goes away while a tool response is
 * in flight, the write fails with EPIPE and the read side ends. Both are normal
 * shutdown, so the child exits quietly instead of crashing and reporting a
 * production error. Any other failure keeps its current crash behaviour.
 */

const CLOSED_PIPE_CODES = new Set(["EPIPE", "ERR_STREAM_DESTROYED"]);

function isClosedPipe(err: unknown): boolean {
  const code = (err as NodeJS.ErrnoException | undefined)?.code;
  return typeof code === "string" && CLOSED_PIPE_CODES.has(code);
}

export function installStdioShutdownGuards(proc: NodeJS.Process): void {
  const exitQuietly = (): void => {
    proc.exit(0);
  };

  // A failure that is not a closed pipe keeps crashing the process: drop the
  // guards, then throw so the default handling reports it.
  const rethrowUnlessClosedPipe = (err: unknown): void => {
    if (isClosedPipe(err)) {
      exitQuietly();
      return;
    }
    proc.removeListener("uncaughtException", rethrowUnlessClosedPipe);
    proc.removeListener("unhandledRejection", rethrowUnlessClosedPipe);
    throw err;
  };

  proc.stdout.on("error", rethrowUnlessClosedPipe);
  proc.stderr.on("error", rethrowUnlessClosedPipe);
  proc.stdin.on("end", exitQuietly);
  proc.stdin.on("close", exitQuietly);
  proc.on("uncaughtException", rethrowUnlessClosedPipe);
  proc.on("unhandledRejection", rethrowUnlessClosedPipe);
}
