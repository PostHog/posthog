import {
  collectDescendants,
  type OsProcess,
  parsePsOutput,
  redactCommand,
} from "@main/watchdog/process-tree";
import { describe, expect, it } from "vitest";

const PS_OUTPUT = [
  "    1     0  12000   0.0 /sbin/launchd",
  "  500     1 850000   3.2 /Applications/PostHog.app/Contents/MacOS/PostHog",
  "  501   500 420000  12.5 /Applications/PostHog.app/Contents/MacOS/PostHog --type=renderer",
  "  502   501 2100000  98.0 node cli.js --api-key sk-ant-abc123def456 --task 42",
  "  900     1  64000   0.1 /usr/bin/unrelated",
].join("\n");

describe("parsePsOutput", () => {
  it("parses pid, ppid, rss and cpu from ps output", () => {
    const processes = parsePsOutput(PS_OUTPUT);

    expect(processes).toHaveLength(5);
    expect(processes[1]).toMatchObject({
      pid: 500,
      ppid: 1,
      // ps reports kilobytes.
      rssBytes: 850000 * 1024,
      cpuPercent: 3.2,
    });
  });

  it("keeps the full command line, spaces and all", () => {
    const renderer = parsePsOutput(PS_OUTPUT).find((p) => p.pid === 501);

    expect(renderer?.command).toBe(
      "/Applications/PostHog.app/Contents/MacOS/PostHog --type=renderer",
    );
  });

  it("ignores header rows and blank lines", () => {
    expect(parsePsOutput("  PID  PPID   RSS %CPU COMMAND\n\n")).toEqual([]);
  });
});

describe("redactCommand", () => {
  it("strips credentials that appear in a command line", () => {
    const redacted = redactCommand(
      "node cli.js --api-key sk-ant-abc123def456 --token phx_supersecrettoken",
    );

    expect(redacted).not.toContain("sk-ant-abc123def456");
    expect(redacted).not.toContain("phx_supersecrettoken");
    expect(redacted).toContain("cli.js");
  });

  it("leaves ordinary arguments alone", () => {
    const command = "/usr/bin/git --no-pager status --porcelain";

    expect(redactCommand(command)).toBe(command);
  });
});

describe("collectDescendants", () => {
  it("returns the root and everything below it, and nothing else", () => {
    const pids = collectDescendants(parsePsOutput(PS_OUTPUT), 500)
      .map((proc) => proc.pid)
      .sort();

    expect(pids).toEqual([500, 501, 502]);
  });

  it("finds agent subprocesses nested under a renderer", () => {
    const agent = collectDescendants(parsePsOutput(PS_OUTPUT), 500).find(
      (proc) => proc.pid === 502,
    );

    expect(agent?.rssBytes).toBe(2100000 * 1024);
  });

  it("returns an empty list when the root is not running", () => {
    expect(collectDescendants(parsePsOutput(PS_OUTPUT), 4242)).toEqual([]);
  });

  it("terminates when a reparented process forms a cycle", () => {
    const cyclic: OsProcess[] = [
      { pid: 10, ppid: 11, rssBytes: 1, cpuPercent: 0, command: "a" },
      { pid: 11, ppid: 10, rssBytes: 1, cpuPercent: 0, command: "b" },
    ];

    expect(collectDescendants(cyclic, 10).map((proc) => proc.pid)).toEqual([
      10, 11,
    ]);
  });
});
