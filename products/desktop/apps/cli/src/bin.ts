#!/usr/bin/env node

import { spawn } from "node:child_process";

const minimumNodeVersion = [26, 4, 0] as const;

function hasSupportedNodeVersion(version: string): boolean {
  const [major = 0, minor = 0, patch = 0] = version
    .replace(/^v/, "")
    .split(".")
    .map(Number);
  const [minimumMajor, minimumMinor, minimumPatch] = minimumNodeVersion;

  return (
    major > minimumMajor ||
    (major === minimumMajor &&
      (minor > minimumMinor ||
        (minor === minimumMinor && patch >= minimumPatch)))
  );
}

function hasExperimentalFfi(): boolean {
  return process.execArgv.includes("--experimental-ffi");
}

async function respawnWithExperimentalFfi(): Promise<number> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(
      process.execPath,
      [
        "--experimental-ffi",
        "--disable-warning=ExperimentalWarning",
        ...process.execArgv,
        process.argv[1],
        ...process.argv.slice(2),
      ],
      {
        env: { ...process.env, HOG_TUI_FFI_RESPAWNED: "1" },
        stdio: "inherit",
      },
    );
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      resolvePromise(code ?? (signal ? 1 : 0));
    });
  });
}

async function run(): Promise<void> {
  if (!hasSupportedNodeVersion(process.versions.node)) {
    process.stderr.write("hog-tui requires Node.js 26.4.0 or later.\n");
    process.exitCode = 1;
    return;
  }

  if (!hasExperimentalFfi()) {
    if (process.env.HOG_TUI_FFI_RESPAWNED === "1") {
      process.stderr.write(
        "hog-tui could not enable Node.js experimental FFI.\n",
      );
      process.exitCode = 1;
      return;
    }
    process.exitCode = await respawnWithExperimentalFfi();
    return;
  }

  const { main } = await import("./app.js");
  await main(process.argv.slice(2));
}

void run().catch((error) => {
  const detail = error instanceof Error ? error.message : "Unknown error";
  process.stderr.write(
    `hog-tui could not start: ${detail}\nInstall the CLI dependencies, then try again.\n`,
  );
  process.exitCode = 1;
});
