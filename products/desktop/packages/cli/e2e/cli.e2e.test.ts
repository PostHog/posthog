import { execFile, execFileSync } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { promisify } from "node:util";
import { describe, expect, it } from "vitest";

const execFileAsync = promisify(execFile);

// Same env contract as packages/agent/e2e/config.ts: a local llm-gateway plus
// a personal API key. Without the token the suite self-skips (never silent).
const GATEWAY_URL =
  process.env.POSTHOG_CODE_E2E_GATEWAY_URL || "http://localhost:3308/ci";
const TOKEN = process.env.POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY ?? "";
const MODEL = process.env.POSTHOG_CODE_E2E_CLAUDE_MODEL || "claude-haiku-4-5";

const CLI_PATH = resolve(__dirname, "../dist/cli.js");

function setupRepo(): string {
  // realpath: on macOS os.tmpdir() is a symlink and the SDK keys its session
  // store by resolved path.
  const repo = realpathSync(mkdtempSync(join(tmpdir(), "code-cli-e2e-")));
  writeFileSync(join(repo, "hello.txt"), "hello\n");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  execFileSync("git", ["add", "-A"], { cwd: repo });
  execFileSync(
    "git",
    [
      "-c",
      "commit.gpgsign=false",
      "-c",
      "user.email=e2e@posthog.dev",
      "-c",
      "user.name=e2e",
      "commit",
      "-qm",
      "init",
    ],
    { cwd: repo },
  );
  return repo;
}

describe.skipIf(!TOKEN)("posthog-code-cli", () => {
  it("runs one turn and prints the answer", async () => {
    expect(
      existsSync(CLI_PATH),
      `CLI not built at ${CLI_PATH} — run pnpm --filter @posthog/code-cli build first`,
    ).toBe(true);
    const repo = setupRepo();
    try {
      const { stdout } = await execFileAsync(
        process.execPath,
        [
          CLI_PATH,
          "Reply with exactly the word OK and nothing else.",
          "--cwd",
          repo,
          "--model",
          MODEL,
        ],
        {
          env: {
            ...process.env,
            ANTHROPIC_BASE_URL: GATEWAY_URL,
            ANTHROPIC_AUTH_TOKEN: TOKEN,
          },
          timeout: 240_000,
        },
      );
      expect(stdout).toContain("OK");
    } finally {
      rmSync(repo, { recursive: true, force: true });
    }
  });
});
