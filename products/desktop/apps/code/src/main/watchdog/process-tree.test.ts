import {
  collectDescendants,
  type OsProcess,
  parsePsOutput,
  redactCommand,
  safeProcessLabel,
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
  it.each([
    [
      "secret flags",
      "node cli.js --api-key sk-ant-abc123def456 --token phx_supersecrettoken",
      ["sk-ant-abc123def456", "phx_supersecrettoken"],
    ],
    [
      "an authorization header",
      `curl -H 'Authorization: Bearer abc123def456' https://example.com`,
      ["abc123def456"],
    ],
    [
      "an api-key header split into argv",
      "curl -H X-Api-Key: abc123def456 https://example.com",
      ["abc123def456"],
    ],
    [
      "credentials in a connection URL",
      "psql postgres://appuser:hunter2hunter2@db.internal:5432/app",
      ["hunter2hunter2"],
    ],
    [
      "an inline environment assignment",
      "sh -c ANTHROPIC_API_KEY=abc123def456 node agent.js",
      ["abc123def456"],
    ],
    [
      "underscored and prefixed secret flags",
      "mcp-server --api_secret abc123def456 --session-token xyz789xyz789",
      ["abc123def456", "xyz789xyz789"],
    ],
    [
      "a token in a URL query string",
      "curl https://example.com/callback?access_token=abc123def456",
      ["abc123def456"],
    ],
  ])("strips %s", (_name, command, secrets) => {
    const redacted = redactCommand(command);

    for (const secret of secrets) {
      expect(redacted).not.toContain(secret);
    }
    expect(redacted).toContain("[redacted]");
  });

  it.each([
    "/usr/bin/git --no-pager status --porcelain",
    // "key" as a substring of an innocent flag must not swallow its value.
    "/Applications/PostHog.app/Contents/MacOS/PostHog --type=renderer --keyboard-layout us",
  ])("leaves ordinary arguments alone: %s", (command) => {
    expect(redactCommand(command)).toBe(command);
  });

  it("keeps enough of the command to identify the process", () => {
    expect(
      redactCommand("node cli.js --api-key sk-ant-abc123def456 --task 42"),
    ).toBe("node cli.js --api-key [redacted] --task 42");
  });
});

describe("safeProcessLabel", () => {
  it("keeps only the executable name, dropping every argument", () => {
    expect(
      safeProcessLabel(
        "/usr/bin/node cli.js --api-key sk-ant-abc123def456 --task 42",
      ),
    ).toBe("node");
  });

  it("keeps Electron's process role, which is a string we ship", () => {
    expect(
      safeProcessLabel(
        "/Applications/PostHog.app/Contents/MacOS/PostHog --type=renderer --enable-features=x",
      ),
    ).toBe("PostHog --type=renderer");
  });

  it.each([
    ["curl -H 'Authorization: Bearer abcdefghijklmnop' https://x", "curl"],
    ["psql postgres://user:hunter2@db.internal/prod", "psql"],
    ["env API_KEY=abcdefghijklmnop ./deploy.sh", "env"],
    ["./run.sh hunter2", "run.sh"],
  ])("drops credentials no denylist would catch: %s", (command, expected) => {
    const label = safeProcessLabel(command);

    expect(label).toBe(expected);
    expect(label).not.toMatch(/hunter2|abcdefghijklmnop/);
  });

  it("falls back to a placeholder for an empty command", () => {
    expect(safeProcessLabel("")).toBe("unknown");
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
