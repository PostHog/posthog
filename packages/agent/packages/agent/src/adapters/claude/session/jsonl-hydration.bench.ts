import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { afterAll, beforeAll, bench, describe } from "vitest";
import { sanitizeSessionJsonl } from "./jsonl-hydration";

// Not run in CI (test globs only match *.test.*). Reproduce with:
//   cd packages/agent && pnpm vitest bench src/adapters/claude/session/jsonl-hydration.bench.ts

const LINES = 50_000;

function makeLine(i: number): string {
  return JSON.stringify({
    type: "assistant",
    uuid: `a-${i}`,
    parentUuid: i === 0 ? null : `a-${i - 1}`,
    message: {
      role: "assistant",
      content: [
        {
          type: "text",
          text: `chunk ${i}: ${"tracing the residency grace period through the rehydration path ".repeat(8)}`,
        },
      ],
    },
  });
}

let dir: string;
let warmPath: string;
let grownPath: string;

beforeAll(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), "sanitize-bench-"));
  const content = `${Array.from({ length: LINES }, (_, i) => makeLine(i)).join("\n")}\n`;
  warmPath = path.join(dir, "warm.jsonl");
  grownPath = path.join(dir, "grown.jsonl");
  await fs.writeFile(warmPath, content);
  await fs.writeFile(grownPath, content);
  // Prime the stat memo for the unchanged-file case.
  await sanitizeSessionJsonl(warmPath);
});

afterAll(async () => {
  await fs.rm(dir, { recursive: true, force: true });
});

describe(`sanitizeSessionJsonl, ${LINES} lines`, () => {
  // Pre-PR behavior on every reconnect, and post-PR behavior whenever the
  // file changed: full read plus a JSON.parse per line. The append inside
  // the run keeps the memo invalidated; its own cost is microseconds.
  bench("file changed since last pass (full read + parse)", async () => {
    await fs.appendFile(grownPath, `${makeLine(LINES)}\n`);
    await sanitizeSessionJsonl(grownPath);
  });

  // This PR: a reconnect against an unchanged file is one fs.stat.
  bench("unchanged file (stat memo hit)", async () => {
    await sanitizeSessionJsonl(warmPath);
  });
});
