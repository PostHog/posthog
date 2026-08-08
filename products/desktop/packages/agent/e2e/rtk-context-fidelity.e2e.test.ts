import { execFileSync } from "node:child_process";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { detectRtkBinary } from "../src/adapters/claude/session/rtk";
import { E2E } from "./config";
import { type Capture, cleanupRepo, openSession, setupRepo } from "./driver";

/**
 * Live RTK context-fidelity e2e (claude arm only — the RTK integration is a
 * deterministic PreToolUse rewrite hook there; codex gets instruction-level
 * guidance the model may or may not follow, so nothing is assertable).
 *
 * The claim under test: routing Bash output through rtk compresses it WITHOUT
 * deleting the information the agent needs — including past rtk's truncation
 * caps, where only the uncapped summary header carries the truth. Each turn
 * forces the agent to recover a specific ground-truth fact (file path, line
 * number, file count, an above-cap match total, git state) from compressed
 * output, across sequential turns in ONE session so compressed context
 * compounds the way long real sessions do. Assertions are deterministic JSON
 * side effects against seeded ground truth — never prose.
 *
 * Anti-skip-to-green: RTK_DB_PATH points rtk's telemetry at a throwaway DB;
 * after the turns, `rtk gain` against that DB must show commands were tracked
 * with positive savings. A run where the hook never engaged (so every fact
 * came from raw output) fails here instead of passing vacuously.
 */

const NEEDLE = "NEEDLE_e2e_7f3a9c";
const NEEDLE_FILE = "src/mod7/service.ts";
const NEEDLE_LINE = 47;
const FIXTURE_COUNT = 9; // *.fixture.md outside vendor/
// 12 dirs × 10 files × 40 lines, every line matching "export const mod" — far
// past rtk grep's 200-shown-results cap, so the only place the true total
// survives compression is the "N matches in M files" header.
const NOISE_MATCH_TOTAL = 12 * 10 * 40;
const MODIFIED_FILES = [
  "src/mod1/file3.ts",
  "src/mod4/file0.ts",
  "src/mod9/file7.ts",
];
const UNTRACKED_FILE = "src/mod2/new-module.ts";

/**
 * Seeds a repo big enough that rtk's compaction engages for real: 120 noise
 * files across 12 dirs (~40 lines each), a needle file, fixture files inside
 * and outside an excluded vendor/ tree.
 */
function seedRepo(repo: string): void {
  for (let m = 0; m < 12; m++) {
    const dir = join(repo, "src", `mod${m}`);
    mkdirSync(dir, { recursive: true });
    for (let f = 0; f < 10; f++) {
      const lines = Array.from(
        { length: 40 },
        (_, l) => `export const mod${m}_file${f}_line${l} = ${l};`,
      );
      writeFileSync(join(dir, `file${f}.ts`), `${lines.join("\n")}\n`);
    }
  }

  const serviceLines = Array.from(
    { length: 80 },
    (_, l) => `export const service_line${l + 1} = ${l + 1};`,
  );
  serviceLines[NEEDLE_LINE - 1] = `export const ${NEEDLE} = "recover-me";`;
  writeFileSync(join(repo, NEEDLE_FILE), `${serviceLines.join("\n")}\n`);

  for (let i = 0; i < FIXTURE_COUNT; i++) {
    writeFileSync(
      join(repo, "src", `mod${i}`, `case${i}.fixture.md`),
      `# fixture ${i}\n`,
    );
  }
  const vendor = join(repo, "vendor", "dep");
  mkdirSync(vendor, { recursive: true });
  for (let i = 0; i < 5; i++) {
    writeFileSync(join(vendor, `vendored${i}.fixture.md`), `# vendored ${i}\n`);
    writeFileSync(join(vendor, `dep${i}.ts`), `export const dep${i} = ${i};\n`);
  }

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
      "seed",
    ],
    { cwd: repo },
  );
}

function readAnswer(repo: string, name: string): Record<string, unknown> {
  const path = join(repo, name);
  expect(existsSync(path), `agent did not write ${name}`).toBe(true);
  return JSON.parse(readFileSync(path, "utf8"));
}

/** The agent may answer "./src/x" or "src/x"; both name the same file. */
function normalizePath(p: unknown): string {
  return String(p).replace(/^\.\//, "");
}

function rtkGainSummary(dbPath: string): Record<string, number> {
  const stdout = execFileSync(
    detectRtkBinary(process.env) as string,
    ["gain", "--format", "json"],
    { encoding: "utf8", env: { ...process.env, RTK_DB_PATH: dbPath } },
  );
  return (JSON.parse(stdout) as { summary: Record<string, number> }).summary;
}

const rtkBinary = detectRtkBinary(process.env);
const skip = E2E.skipReason("claude") ?? (rtkBinary ? null : "rtk not on PATH");
const title = `rtk context fidelity (claude)${skip ? ` — SKIPPED (${skip})` : ""}`;

describe.skipIf(!!skip)(title, () => {
  let repo: string;
  let rtkDbPath: string;
  let savedRtkDbPath: string | undefined;
  const turns: Array<{ stopReason?: string; capture: Capture }> = [];
  let turnError: unknown;

  beforeAll(async () => {
    E2E.configureEnv("claude");
    repo = setupRepo();
    seedRepo(repo);
    // Isolate rtk telemetry to this run so the engagement assertion cannot be
    // satisfied by a developer's ambient rtk history. Sibling of the repo, not
    // inside it — the DB must not appear in turn 3's untracked ground truth.
    rtkDbPath = `${repo}-rtk-gain.db`;
    savedRtkDbPath = process.env.RTK_DB_PATH;
    process.env.RTK_DB_PATH = rtkDbPath;

    const s = await openSession({
      adapter: "claude",
      cwd: repo,
      meta: {
        systemPrompt:
          "You are a coding assistant in a test repo. Follow instructions exactly.",
        model: E2E.model("claude"),
        permissionMode: "bypassPermissions",
        taskRunId: "e2e-rtk-fidelity",
      },
    });

    const prompts = [
      // Turn 1 — grep recovery: file + line number must survive compression.
      `Step 1: run exactly this single Bash command: grep -rn "${NEEDLE}" src\n` +
        `Step 2: from its output, write a file named answer-grep.json containing ` +
        `exactly {"file": "<relative path of the file containing ${NEEDLE}>", "line": <line number as an integer>}. ` +
        `Do nothing else, then stop.`,
      // Turn 2 — find with -not (rtk-unsupported predicate): the guard must
      // leave it raw, so the complete list arrives and the count is exact.
      `Step 1: run exactly this single Bash command: find . -type f -name "*.fixture.md" -not -path "./vendor/*"\n` +
        `Step 2: count the files in its output and write a file named answer-find.json containing ` +
        `exactly {"count": <integer>}. Do nothing else, then stop.`,
      // Turn 3 — the lossy threshold: thousands of matches, far past rtk's
      // 200-shown cap. The exact total only survives in the summary header.
      `Step 1: run exactly this single Bash command: grep -rn "export const mod" src\n` +
        `Step 2: from its output, determine the TOTAL number of matches (the output may show ` +
        `a summary with the total alongside a subset of matches) and write a file named ` +
        `answer-count.json containing exactly {"matches": <integer>}. Do nothing else, then stop.`,
      // Turn 4 — chained git segments: per-file status must survive compression.
      `Step 1: run exactly this single Bash command: git status && git diff --stat\n` +
        `Step 2: from its output, write a file named answer-git.json containing exactly ` +
        `{"modified": [<relative paths of modified tracked files, sorted>], ` +
        `"untracked": [<relative paths of untracked files, sorted>]}. ` +
        `Exclude answer-grep.json, answer-find.json and answer-count.json from both lists. Do nothing else, then stop.`,
    ];

    try {
      for (const [i, text] of prompts.entries()) {
        // Mutate the worktree before the git turn so it has real state.
        if (i === 3) {
          for (const file of MODIFIED_FILES) {
            appendFileSync(join(repo, file), "export const changed = true;\n");
          }
          writeFileSync(
            join(repo, UNTRACKED_FILE),
            "export const fresh = true;\n",
          );
        }
        const res = await s.conn.prompt({
          sessionId: s.sessionId,
          prompt: [{ type: "text", text }],
        });
        turns.push({ stopReason: res.stopReason, capture: s.capture });
      }
    } catch (err) {
      turnError = err;
    } finally {
      await s.cleanup();
    }
  }, 360_000);

  afterAll(() => {
    // Guarded: a beforeAll that throws before assignment must not have its
    // real failure masked by cleanup throwing on undefined paths.
    if (savedRtkDbPath === undefined) delete process.env.RTK_DB_PATH;
    else process.env.RTK_DB_PATH = savedRtkDbPath;
    if (repo) cleanupRepo(repo);
    if (rtkDbPath) {
      for (const suffix of ["", "-wal", "-shm"]) {
        rmSync(`${rtkDbPath}${suffix}`, { force: true });
      }
    }
  });

  it("completes all four turns", () => {
    if (turnError) throw turnError;
    expect(turns).toHaveLength(4);
    for (const t of turns) expect(t.stopReason).toBe("end_turn");
  });

  it("recovers an exact file + line number from compressed grep output", () => {
    if (turnError) throw turnError;
    const answer = readAnswer(repo, "answer-grep.json");
    expect(normalizePath(answer.file)).toBe(NEEDLE_FILE);
    expect(answer.line).toBe(NEEDLE_LINE);
  });

  it("recovers an exact file count from a guarded (raw) find -not", () => {
    if (turnError) throw turnError;
    const answer = readAnswer(repo, "answer-find.json");
    expect(answer.count).toBe(FIXTURE_COUNT);
  });

  // The lossy threshold the small turns sail under: rtk grep shows at most
  // 200 matches, so the agent can only get the exact total from the uncapped
  // summary header. This is the discoverability contract at real scale.
  it("recovers the exact match total past rtk's truncation cap", () => {
    if (turnError) throw turnError;
    const answer = readAnswer(repo, "answer-count.json");
    expect(answer.matches).toBe(NOISE_MATCH_TOTAL);
  });

  it("recovers per-file git state from a compressed && chain", () => {
    if (turnError) throw turnError;
    const answer = readAnswer(repo, "answer-git.json");
    const modified = (answer.modified as unknown[]).map(normalizePath).sort();
    const untracked = (answer.untracked as unknown[]).map(normalizePath);
    expect(modified).toEqual([...MODIFIED_FILES].sort());
    expect(untracked).toContain(UNTRACKED_FILE);
  });

  // The teeth: rtk's own telemetry must show the hook engaged with real
  // savings. Without this, a disabled hook would pass every fact check above
  // against raw output and the suite would prove nothing about compression.
  it("routed the session's commands through rtk with positive savings", () => {
    if (turnError) throw turnError;
    const summary = rtkGainSummary(rtkDbPath);
    expect(summary.total_commands).toBeGreaterThanOrEqual(3);
    expect(summary.total_saved).toBeGreaterThan(0);
  });
});
