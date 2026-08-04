import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LOCAL_TOOLS_MCP_NAME } from "../local-tools";
import { buildLocalToolsServer } from "./local-tools-mcp";

// The dist asset isn't on the walk-up path in unit tests, so make existsSync
// succeed; nothing spawns the script — we only inspect the path.
vi.mock("node:fs", async (importActual) => {
  const actual = await importActual<typeof import("node:fs")>();
  return { ...actual, existsSync: vi.fn().mockReturnValue(true) };
});

describe("buildLocalToolsServer", () => {
  const saved = {
    sandbox: process.env.IS_SANDBOX,
    ghToken: process.env.GH_TOKEN,
    githubToken: process.env.GITHUB_TOKEN,
  };

  beforeEach(() => {
    // The signed-git gate reads IS_SANDBOX and the token vars; clear them so each
    // case controls the cloud signal (meta.environment) and token explicitly.
    delete process.env.IS_SANDBOX;
    delete process.env.GH_TOKEN;
    delete process.env.GITHUB_TOKEN;
  });

  afterEach(() => {
    restore("IS_SANDBOX", saved.sandbox);
    restore("GH_TOKEN", saved.ghToken);
    restore("GITHUB_TOKEN", saved.githubToken);
  });

  function restore(key: string, value: string | undefined): void {
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }

  it("returns a stdio server config with command/args/env on a cloud run with a token", () => {
    process.env.GH_TOKEN = "ghs_test";

    const server = buildLocalToolsServer(
      { cwd: "/repo" },
      {
        environment: "cloud",
        taskId: "task-1",
        taskRunId: "run-1",
        baseBranch: "master",
      },
    );

    expect(server).not.toBeNull();
    expect(server?.name).toBe(LOCAL_TOOLS_MCP_NAME);
    expect(server?.command).toBe(process.execPath);
    expect(server?.args).toHaveLength(1);
    expect(server?.args[0]).toMatch(/local-tools-mcp-server\.js$/);

    const envNames = server?.env.map((e) => e.name) ?? [];
    expect(envNames).toContain("POSTHOG_LOCAL_TOOLS_CTX");
    expect(envNames).toContain("POSTHOG_LOCAL_TOOLS_ENABLED");
    // Token is forwarded to the child so its own git remote ops authenticate.
    expect(envNames).toContain("GH_TOKEN");
    expect(envNames).toContain("GITHUB_TOKEN");
    // Codex strips ELECTRON_RUN_AS_NODE from its own env, and process.execPath
    // is the app binary in packaged installs; without this the server boots
    // the full desktop app instead of running the script.
    expect(server?.env).toContainEqual({
      name: "ELECTRON_RUN_AS_NODE",
      value: "1",
    });

    const ctxEntry = server?.env.find(
      (e) => e.name === "POSTHOG_LOCAL_TOOLS_CTX",
    );
    const ctx = JSON.parse(
      Buffer.from(ctxEntry?.value ?? "", "base64").toString("utf-8"),
    );
    expect(ctx.cwd).toBe("/repo");
    expect(ctx.token).toBe("ghs_test");
    expect(ctx.taskId).toBe("task-1");
    expect(ctx.taskRunId).toBe("run-1");
    expect(ctx.baseBranch).toBe("master");
  });

  it("returns a server but omits token env vars when no token is present", () => {
    const server = buildLocalToolsServer(
      { cwd: "/repo" },
      { environment: "cloud" },
    );

    expect(server).not.toBeNull();
    const envNames = server?.env.map((e) => e.name) ?? [];
    expect(envNames).toContain("POSTHOG_LOCAL_TOOLS_CTX");
    expect(envNames).not.toContain("GH_TOKEN");
    expect(envNames).not.toContain("GITHUB_TOKEN");
  });

  it("returns null when no cwd is present", () => {
    process.env.GH_TOKEN = "ghs_test";

    expect(
      buildLocalToolsServer({ cwd: undefined }, { environment: "cloud" }),
    ).toBeNull();
  });

  it("exposes speak on a desktop run with narration on (no cloud-only tools)", () => {
    process.env.GH_TOKEN = "ghs_test";

    const server = buildLocalToolsServer(
      { cwd: "/repo" },
      { environment: "local", spokenNarration: true },
    );

    expect(server).not.toBeNull();
    const enabled =
      server?.env.find((e) => e.name === "POSTHOG_LOCAL_TOOLS_ENABLED")
        ?.value ?? "";
    const names = enabled.split(",");
    expect(names).toContain("speak");
    // Signed-git tools are cloud-only and must not leak into a desktop run.
    expect(names).not.toContain("git_signed_commit");
  });

  it("returns null on a desktop run with narration off (no tools pass their gate)", () => {
    process.env.GH_TOKEN = "ghs_test";

    expect(
      buildLocalToolsServer({ cwd: "/repo" }, { environment: "local" }),
    ).toBeNull();
  });
});
