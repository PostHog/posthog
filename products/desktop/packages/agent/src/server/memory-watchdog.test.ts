import {
  appendFile,
  mkdtemp,
  open,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProcessKilledParams } from "../acp-extensions";
import { Logger } from "../utils/logger";
import {
  CliProcessRegistry,
  JsonlTail,
  MemoryWatchdogWatcher,
  toProcessKilledParams,
} from "./memory-watchdog";

const KILL_RECORD = {
  event: "kill",
  ts: 1_767_225_600.5,
  pid: 4242,
  comm: "vitest",
  cmdline: "node /workspace/node_modules/.bin/vitest run",
  tree_rss: 12_884_901_888,
  signal: "SIGTERM",
  current: 14_602_888_806,
  limit: 17_179_869_184,
  candidate_count: 2,
};

const KILL_PARAMS: ProcessKilledParams = {
  pid: 4242,
  comm: "vitest",
  treeRssBytes: 12_884_901_888,
  memoryCurrentBytes: 14_602_888_806,
  memoryLimitBytes: 17_179_869_184,
  signal: "SIGTERM",
  at: "2026-01-01T00:00:00.500Z",
};

describe("memory watchdog", () => {
  it.each([
    {
      name: "a line split across two reads",
      chunks: ['{"event":"kill","pid"', ":1}\n"],
      expected: [[], [{ event: "kill", pid: 1 }]],
    },
    {
      name: "several lines in one read",
      chunks: ['{"a":1}\n{"b":2}\n'],
      expected: [[{ a: 1 }, { b: 2 }]],
    },
    {
      name: "a trailing partial line held until its newline",
      chunks: ['{"a":1}\n{"b"', ":2}\n"],
      expected: [[{ a: 1 }], [{ b: 2 }]],
    },
    {
      name: "a multibyte character split across reads",
      chunks: [
        Buffer.from('{"comm":"né"}\n').subarray(0, 11),
        Buffer.from('{"comm":"né"}\n').subarray(11),
      ],
      expected: [[], [{ comm: "né" }]],
    },
    {
      name: "malformed and blank lines skipped",
      chunks: ['not json\n\n[1]\n{"a":1}\n'],
      expected: [[{ a: 1 }]],
    },
  ])("tails $name", ({ chunks, expected }) => {
    const tail = new JsonlTail();
    const results = chunks.map((chunk) =>
      tail.consume(typeof chunk === "string" ? Buffer.from(chunk) : chunk),
    );

    expect(results).toEqual(expected);
    expect(tail.position).toBe(
      chunks.reduce(
        (total, chunk) =>
          total +
          (typeof chunk === "string" ? Buffer.byteLength(chunk) : chunk.length),
        0,
      ),
    );
  });

  it.each([
    { name: "a kill record", record: KILL_RECORD, expected: KILL_PARAMS },
    {
      name: "a numeric signal",
      record: { ...KILL_RECORD, signal: 9, cmdline: ["node", "big.js"] },
      expected: { ...KILL_PARAMS, signal: "SIGKILL" },
    },
    {
      name: "a pressure record",
      record: { ...KILL_RECORD, event: "pressure" },
      expected: null,
    },
    {
      name: "a kill record without sizes",
      record: { ...KILL_RECORD, tree_rss: undefined },
      expected: null,
    },
    {
      name: "a kill record without comm",
      record: { ...KILL_RECORD, comm: 7 },
      expected: null,
    },
  ])("maps $name", ({ record, expected }) => {
    expect(toProcessKilledParams(record)).toEqual(expected);
  });

  describe("watcher", () => {
    let dir: string;
    let path: string;

    beforeEach(async () => {
      dir = await mkdtemp(join(tmpdir(), "memory-watchdog-"));
      path = join(dir, "events.jsonl");
    });

    afterEach(async () => {
      await rm(dir, { recursive: true, force: true });
    });

    it("reports each kill once across appends, a missing file, truncation and replacement", async () => {
      const onProcessKilled = vi.fn();
      const watcher = new MemoryWatchdogWatcher({
        onProcessKilled,
        logger: new Logger({ debug: false }),
        path,
      });

      await watcher.poll();
      await writeFile(
        path,
        `${JSON.stringify({ event: "watchdog_started", ts: 1 })}\n${JSON.stringify(KILL_RECORD).slice(0, 20)}`,
      );
      await watcher.poll();
      await appendFile(path, `${JSON.stringify(KILL_RECORD).slice(20)}\n`);
      await watcher.poll();
      await watcher.poll();
      await writeFile(path, `${JSON.stringify({ ...KILL_RECORD, pid: 7 })}\n`);
      await watcher.poll();
      const keep = await open(path, "r");
      await rm(path);
      await writeFile(
        path,
        `${JSON.stringify({ event: "watchdog_started", ts: 2 })}\n${JSON.stringify({ ...KILL_RECORD, pid: 8 })}\n`,
      );
      await watcher.poll();
      await keep.close();

      expect(onProcessKilled.mock.calls).toEqual([
        [KILL_PARAMS],
        [{ ...KILL_PARAMS, pid: 7 }],
        [{ ...KILL_PARAMS, pid: 8 }],
      ]);
    });

    it.each([
      {
        name: "keeps the other pid after one of two exits",
        steps: [
          ["spawned", 11],
          ["spawned", 12],
          ["exited", 11],
        ],
        expected: "12\n",
      },
      {
        name: "ignores an exit for an unknown pid",
        steps: [
          ["spawned", 11],
          ["exited", 99],
        ],
        expected: "11\n",
      },
      {
        name: "writes an empty file after the last exit",
        steps: [
          ["spawned", 11],
          ["exited", 11],
        ],
        expected: "",
      },
    ] as const)("cli pid file $name", async ({ steps, expected }) => {
      const pidPath = join(dir, "agent-cli.pid");
      const registry = new CliProcessRegistry({}, pidPath);

      await Promise.all(steps.map(([action, pid]) => registry[action](pid)));

      expect(await readFile(pidPath, "utf8")).toBe(expected);
    });
  });
});
