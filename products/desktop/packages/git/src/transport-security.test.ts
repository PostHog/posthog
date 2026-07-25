import { execFile } from "node:child_process";
import { chmod, mkdtemp, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createGitClient } from "./client";
import { fetchRef } from "./queries";
import {
  GIT_TRANSPORT_SECURITY_CONFIG,
  gitTransportSecurityArgs,
} from "./transport-security";

const execFileAsync = promisify(execFile);

describe("git transport security policy", () => {
  it("denies the ext transport and pins file to user", () => {
    expect(GIT_TRANSPORT_SECURITY_CONFIG).toEqual([
      "protocol.ext.allow=never",
      "protocol.file.allow=user",
    ]);
  });

  it("renders `-c key=value` argv for raw git seams", () => {
    expect(gitTransportSecurityArgs()).toEqual([
      "-c",
      "protocol.ext.allow=never",
      "-c",
      "protocol.file.allow=user",
    ]);
  });
});

// End-to-end proof that the fetch the app runs on task/worktree creation cannot
// be turned into RCE by a malicious `.git/config` whose origin is an `ext::`
// remote (which git would otherwise run as a shell command).
describe("ext:: remote fetch hardening", () => {
  let dir: string;
  let marker: string;

  beforeEach(async () => {
    dir = await mkdtemp(path.join(tmpdir(), "posthog-code-transport-"));
    marker = path.join(dir, "pwned");
    const script = path.join(dir, "evil.sh");
    // The ext transport execs this script; if it runs, the marker appears.
    await writeFile(script, `#!/bin/sh\ntouch "${marker}"\nexit 1\n`);
    await chmod(script, 0o755);
    const git = createGitClient(dir);
    await git.init(["--initial-branch", "main"]);
    await git.addConfig("user.name", "Test");
    await git.addConfig("user.email", "test@example.com");
    await git.raw(["remote", "add", "origin", `ext::${script}`]);
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  const markerExists = async (): Promise<boolean> => {
    try {
      await stat(marker);
      return true;
    } catch {
      return false;
    }
  };

  it("positive control: git runs the ext command when the transport is allowed", async () => {
    // Baseline proving the malicious remote really is wired to execute code, so
    // the "blocked" assertions below cannot pass vacuously. upload-pack exits 1
    // after the marker is created; we only assert the command ran.
    await execFileAsync(
      "git",
      [
        "-c",
        "protocol.ext.allow=user",
        "fetch",
        "--quiet",
        "--no-tags",
        "origin",
        "--",
        "main",
      ],
      { cwd: dir },
    ).catch(() => {});
    expect(await markerExists()).toBe(true);
  });

  it("fetchRef refuses the ext transport and runs no command", async () => {
    const errors: string[] = [];
    const ok = await fetchRef(createGitClient(dir), "origin", "main", {
      onError: (message) => errors.push(message),
    });
    expect(ok).toBe(false);
    expect(errors.join("\n")).toMatch(/transport 'ext' not allowed/);
    expect(await markerExists()).toBe(false);
  });

  it("caller-supplied config cannot re-enable the ext transport", async () => {
    // Security config is spread last, so it overrides a caller trying to relax
    // `protocol.ext.allow` back to the exploitable default.
    const git = createGitClient(dir, { config: ["protocol.ext.allow=user"] });
    await expect(
      git.raw(["fetch", "--quiet", "--no-tags", "origin", "--", "main"]),
    ).rejects.toThrow(/transport 'ext' not allowed/);
    expect(await markerExists()).toBe(false);
  });

  it("still reaches git on a remote task instead of tripping simple-git's guard", async () => {
    // simple-git refuses `protocol.*` config on remote tasks unless
    // `unsafe.allowUnsafeProtocolOverride` is set (client.ts). Without it every
    // fetch, clone and ls-remote in the app throws before git runs, so assert
    // the rejection comes from git's transport policy and not from that guard.
    const git = createGitClient(dir);
    await expect(git.raw(["ls-remote", "origin"])).rejects.not.toThrow(
      /allowUnsafeProtocolOverride/,
    );
  });
});
