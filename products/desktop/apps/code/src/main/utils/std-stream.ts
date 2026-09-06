import type { Writable } from "node:stream";

// Codes that mean the reader on the other end of stdout/stderr is gone: the
// terminal closed, the parent process exited, or a shell pipeline ended.
const DEAD_PIPE_CODES = new Set(["EPIPE", "ERR_STREAM_DESTROYED"]);

function isDeadPipeError(error: unknown): boolean {
  return (
    error instanceof Error &&
    DEAD_PIPE_CODES.has((error as NodeJS.ErrnoException).code ?? "")
  );
}

// A failed write to a dead stdout/stderr pipe surfaces asynchronously as an
// "error" event on the stream. Without a listener Node re-throws it as an
// uncaught exception in the main process, which kills the whole app. Swallow
// the dead-pipe codes so a closed pipe only loses log output.
export function installStdStreamGuards(): void {
  for (const stream of [process.stdout, process.stderr]) {
    stream.on("error", (error) => {
      if (isDeadPipeError(error)) return;
      throw error;
    });
  }
}

// Writes to a stream that is already destroyed throw synchronously, which the
// stream "error" guard cannot catch. Wrap the write so a dead pipe drops the
// chunk instead of crashing the process.
export function safeStreamWrite(
  stream: Writable,
  chunk: Buffer | string,
): void {
  try {
    stream.write(chunk);
  } catch (error) {
    if (isDeadPipeError(error)) return;
    throw error;
  }
}
