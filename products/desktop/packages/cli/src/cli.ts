#!/usr/bin/env node
import { parseCliArgs } from "./args";
import { run } from "./run";

async function readStdin(): Promise<string> {
  const parts: Buffer[] = [];
  for await (const part of process.stdin) {
    parts.push(part as Buffer);
  }
  return Buffer.concat(parts).toString("utf8");
}

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
    prompt = (await readStdin()).trim();
  }
  if (!prompt) {
    process.stderr.write(
      "No prompt given. Pass one as an argument or pipe it on stdin.\n",
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

// The agent subprocess can leave handles open past cleanup; force-exit once
// output has flushed. unref lets a clean event loop exit naturally first.
function exitAfterFlush(code: number): void {
  process.exitCode = code;
  setTimeout(() => process.exit(code), 500).unref();
}

main().then(exitAfterFlush, (err) => {
  const message = err instanceof Error ? err.message : String(err);
  process.stderr.write(`posthog-code-cli: ${message}\n`);
  exitAfterFlush(1);
});
