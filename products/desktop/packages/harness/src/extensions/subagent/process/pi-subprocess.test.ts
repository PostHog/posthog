import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  nodeCompatibleSpawnEnv,
  piCliInvocation,
  resolvePiCliEntry,
} from "./pi-subprocess";

describe("resolvePiCliEntry", () => {
  it("resolves to cli.js next to the installed @earendil-works/pi-coding-agent package", () => {
    const entry = resolvePiCliEntry();
    expect(entry.endsWith(`${join("", "cli.js")}`)).toBe(true);
    // Sibling of the package's main entry point, not some unrelated path.
    expect(dirname(entry).length).toBeGreaterThan(0);
  });
});

describe("nodeCompatibleSpawnEnv", () => {
  it("sets ELECTRON_RUN_AS_NODE=1 without dropping other env vars", () => {
    const env = nodeCompatibleSpawnEnv({ FOO: "bar" });
    expect(env.ELECTRON_RUN_AS_NODE).toBe("1");
    expect(env.FOO).toBe("bar");
  });

  it("overrides an existing ELECTRON_RUN_AS_NODE value", () => {
    const env = nodeCompatibleSpawnEnv({ ELECTRON_RUN_AS_NODE: "0" });
    expect(env.ELECTRON_RUN_AS_NODE).toBe("1");
  });

  it("defaults to process.env when no env is passed", () => {
    const env = nodeCompatibleSpawnEnv();
    expect(env.ELECTRON_RUN_AS_NODE).toBe("1");
    expect(env.PATH ?? env.Path).toBeTruthy();
  });
});

describe("piCliInvocation", () => {
  it("builds command/args/env for spawning pi's CLI with the given args", () => {
    const invocation = piCliInvocation(["--mode", "json", "-p", "hello"], {
      FOO: "bar",
    });
    expect(invocation.command).toBe(process.execPath);
    expect(invocation.args[0]).toBe(resolvePiCliEntry());
    expect(invocation.args.slice(1)).toEqual(["--mode", "json", "-p", "hello"]);
    expect(invocation.env.ELECTRON_RUN_AS_NODE).toBe("1");
    expect(invocation.env.FOO).toBe("bar");
  });

  it("passes an empty args array through unchanged aside from the cli entry", () => {
    const invocation = piCliInvocation([]);
    expect(invocation.args).toEqual([resolvePiCliEntry()]);
  });
});
