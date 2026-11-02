import { appendFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { captureException } from "./analytics";

// Ink owns the screen, so the TUI and Vite write their logs here.
export const LOG_PATH = join(tmpdir(), "posthog-tui.log");

export const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

// Writes an error the screen cannot show to the log, with its stack.
export function logError(scope: string, error: unknown): void {
  captureException(error, { scope });
  const detail =
    error instanceof Error ? (error.stack ?? error.message) : String(error);
  try {
    appendFileSync(
      LOG_PATH,
      `${new Date().toISOString()} error [${scope}] ${detail}\n`,
    );
  } catch {
    // A log that cannot be written must not take the app down with it.
  }
}
