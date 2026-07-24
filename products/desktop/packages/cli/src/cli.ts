#!/usr/bin/env node
import { text } from "node:stream/consumers";
import { parseCliArgs } from "./args";
import { run } from "./run";

async function main(): Promise<number> {
  const parsed = parseCliArgs(process.argv);
  if ("error" in parsed) {
    if (parsed.error) {
      process.stderr.write(`${parsed.error}\n`);
    }
    return parsed.exitCode;
  }

  let prompt = parsed.prompt;
  if (!prompt && !process.stdin.isTTY) {
    prompt = (await text(process.stdin)).trim();
  }
  if (!prompt) {
    process.stderr.write(
      "No prompt given. Pass one as an argument or pipe it on stdin.\n",
    );
    return 1;
  }

  // The Claude subprocess refuses bypass for root outside a sandbox; fail
  // here with a clear message instead of a cryptic session error.
  if (
    parsed.permissionMode === "bypassPermissions" &&
    process.getuid?.() === 0 &&
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

  return run({ ...parsed, prompt });
}

// process.exit does not wait for pending pipe writes, so flush stdout first
// (the write callback fires once earlier writes are accepted by the OS).
// The agent subprocess can leave handles open past cleanup; the unref'd timer
// force-exits then, while a clean event loop still exits naturally. The
// unconditional backstop covers a stalled consumer that never drains the pipe,
// which would otherwise keep the flush callback from ever firing.
function exitAfterFlush(code: number): void {
  process.exitCode = code;
  setTimeout(() => process.exit(code), 10_000).unref();
  process.stdout.write("", () => {
    setTimeout(() => process.exit(code), 500).unref();
  });
}

main().then(exitAfterFlush, (err) => {
  const message = err instanceof Error ? err.message : String(err);
  process.stderr.write(`posthog-code-cli: ${message}\n`);
  exitAfterFlush(1);
});
