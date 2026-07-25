#!/usr/bin/env node
import { text } from "node:stream/consumers";
import { withTimeout } from "@posthog/shared";
import { parseCliArgs } from "./args";
import { run } from "./run";

// A reader that exits early (`… | head -1`) closes the pipe under us. Without a
// listener the next write raises an unhandled 'error' event, which crashes with
// a raw stack trace before cleanup can run. Swallowing it lets the run unwind
// through its normal teardown, so the agent subprocess still gets torn down;
// further writes are discarded, and the force-exit backstop covers the flush
// callback that a closed pipe will never fire. Registered before any output.
process.stdout.on("error", (err: NodeJS.ErrnoException) => {
  if (err.code !== "EPIPE") throw err;
});

// A non-TTY stdin that never reaches EOF (an inherited but idle stdin under a
// supervisor or CI step) must not hang a one-shot run.
const STDIN_READ_TIMEOUT_MS = 30_000;

async function main(): Promise<number> {
  const parsed = parseCliArgs(process.argv);
  if (parsed.kind === "exit") return parsed.exitCode;
  if (parsed.kind === "error") {
    process.stderr.write(`${parsed.message}\n`);
    return 1;
  }
  const { options } = parsed;

  let prompt = options.prompt?.trim();
  if (!prompt && !process.stdin.isTTY) {
    const piped = await withTimeout(text(process.stdin), STDIN_READ_TIMEOUT_MS);
    if (piped.result === "success") {
      prompt = piped.value.trim();
    } else {
      // The read is still pending and holds the event loop open.
      process.stdin.destroy();
    }
  }
  if (!prompt) {
    process.stderr.write(
      "No prompt given. Pass one as an argument or pipe it on stdin.\n",
    );
    return 1;
  }

  // The Claude subprocess refuses bypass for root outside a sandbox; fail
  // here with a clear message instead of a cryptic session error. Effective uid
  // first, matching the IS_ROOT check in @posthog/agent that actually gates it.
  if (
    options.permissionMode === "bypassPermissions" &&
    (process.geteuid?.() ?? process.getuid?.()) === 0 &&
    !process.env.IS_SANDBOX
  ) {
    process.stderr.write(
      "--permission-mode bypassPermissions is unavailable when running as root unless IS_SANDBOX=1 is set.\n",
    );
    return 1;
  }

  if (!process.env.ANTHROPIC_API_KEY && !process.env.ANTHROPIC_AUTH_TOKEN) {
    process.stderr.write(
      "Warning: neither ANTHROPIC_API_KEY nor ANTHROPIC_AUTH_TOKEN is set; " +
        "relying on a stored claude login credential.\n",
    );
  }

  return run({ ...options, prompt });
}

// The agent subprocess can leave handles open past cleanup, so force-exit once
// stdout has drained; a clean event loop still exits naturally before then.
const POST_FLUSH_GRACE_MS = 500;
// Backstop for a consumer that never drains the pipe, which would otherwise
// keep the flush callback from ever firing.
const STALLED_CONSUMER_TIMEOUT_MS = 10_000;

// process.exit does not wait for pending pipe writes, so flush stdout first
// (the write callback fires once earlier writes are accepted by the OS).
function exitAfterFlush(code: number): void {
  process.exitCode = code;
  setTimeout(() => process.exit(code), STALLED_CONSUMER_TIMEOUT_MS).unref();
  process.stdout.write("", () => {
    setTimeout(() => process.exit(code), POST_FLUSH_GRACE_MS).unref();
  });
}

main().then(exitAfterFlush, (err) => {
  // parsed.debug is out of scope here, and an unexpected throw is exactly when
  // the stack is worth having.
  const detail =
    err instanceof Error
      ? (process.argv.includes("--debug") && err.stack) || err.message
      : String(err);
  process.stderr.write(`posthog-code-cli: ${detail}\n`);
  exitAfterFlush(1);
});
