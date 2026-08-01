import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import {
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

const OUT_DIR = path.join(__dirname, "../../../out");

export const PRISTINE_APP = path.join(OUT_DIR, "mac-arm64/PostHog.app");
export const FEED_DIR = path.join(OUT_DIR, "dev-update-feed");
export const RUN_DIR = path.join(OUT_DIR, "e2e-update-run");
export const RUN_APP = path.join(RUN_DIR, "PostHog.app");
export const RUN_APP_BIN = path.join(RUN_APP, "Contents/MacOS/PostHog");

// The "old" side of the Forge -> electron-builder test: a real Electron Forge
// build (v0.55.132) produced by scripts/dev-update/build-old-forge.sh. It runs
// the genuine built-in Squirrel.Mac client, against the same 2.0.0 feed.
export const FORGE_PRISTINE_APP = path.join(
  OUT_DIR,
  "old-forge/PostHog Code.app",
);
export const FORGE_RUN_DIR = path.join(OUT_DIR, "e2e-update-forge-run");
export const FORGE_RUN_APP = path.join(FORGE_RUN_DIR, "PostHog Code.app");
export const FORGE_RUN_APP_BIN = path.join(
  FORGE_RUN_APP,
  "Contents/MacOS/PostHog Code",
);
// Squirrel installs the update under the update bundle's own name, so the swap renames the .app on disk.
export const FORGE_RUN_APP_UPDATED = path.join(
  FORGE_RUN_DIR,
  path.basename(RUN_APP),
);
export const FORGE_RUN_APP_BIN_UPDATED = path.join(
  FORGE_RUN_APP_UPDATED,
  "Contents/MacOS",
  path.basename(RUN_APP_BIN),
);

export const MAIN_LOG = path.join(homedir(), ".posthog-code/logs/main.log");
export const SHIPIT_DIR = path.join(
  homedir(),
  "Library/Caches/com.posthog.array.ShipIt",
);

export const PROOF_DIR = path.join(OUT_DIR, "update-proof");
const PROOF_FILE = path.join(PROOF_DIR, "proof.json");

export const FORGE_PROOF_DIR = path.join(OUT_DIR, "update-proof-forge");
const FORGE_PROOF_FILE = path.join(FORGE_PROOF_DIR, "proof.json");

const SERVE_SCRIPT = path.join(
  __dirname,
  "../../../scripts/dev-update/serve.mjs",
);

// A single legible record of the update, written on pass and fail, that the
// workflow turns into a run-page summary and uploads as the proof artifact.
export type UpdateProof = {
  result: "PASS" | "FAIL";
  oldVersion: string;
  newVersion: string;
  bootedOn?: string;
  feedAvailableVersion?: string;
  downloaded?: boolean;
  bundleVersionAfterSwap?: string;
  autoRelaunchedExecutable?: string;
  freshLaunchVersion?: string;
  shipItExists?: boolean;
  shipItEntries?: string[];
  failedStep?: string;
  error?: string;
  finishedAt?: string;
};

export function writeProof(proof: UpdateProof): void {
  mkdirSync(PROOF_DIR, { recursive: true });
  writeFileSync(PROOF_FILE, `${JSON.stringify(proof, null, 2)}\n`);
}

export function writeForgeProof(proof: UpdateProof): void {
  mkdirSync(FORGE_PROOF_DIR, { recursive: true });
  writeFileSync(FORGE_PROOF_FILE, `${JSON.stringify(proof, null, 2)}\n`);
}

// Copy the pristine built app into a disposable run dir so the in-place update
// swap never mutates the build output, which lets a retry start from 1.0.0
// again. ditto preserves the code signature that Squirrel.Mac verifies.
export function prepareRunApp(): void {
  rmSync(RUN_DIR, { recursive: true, force: true });
  mkdirSync(RUN_DIR, { recursive: true });
  execFileSync("ditto", [PRISTINE_APP, RUN_APP]);
}

export function prepareForgeRunApp(): void {
  rmSync(FORGE_RUN_DIR, { recursive: true, force: true });
  mkdirSync(FORGE_RUN_DIR, { recursive: true });
  execFileSync("ditto", [FORGE_PRISTINE_APP, FORGE_RUN_APP]);
}

export function startFeedServer(port: number): ChildProcess {
  return spawn("node", [SERVE_SCRIPT, FEED_DIR, String(port)], {
    stdio: "inherit",
  });
}

export function readBundleVersion(appPath: string): string {
  return execFileSync(
    "plutil",
    [
      "-extract",
      "CFBundleShortVersionString",
      "raw",
      path.join(appPath, "Contents/Info.plist"),
    ],
    { encoding: "utf8" },
  ).trim();
}

export function readBundleVersionIfPresent(appPath: string): string | null {
  try {
    return readBundleVersion(appPath);
  } catch {
    return null;
  }
}

export function readMainLog(): string {
  try {
    return readFileSync(MAIN_LOG, "utf8");
  } catch {
    return "";
  }
}

// Both legs swap the same bundle id, so they share one ShipIt cache dir. Clear it
// before a run that asserts on it, so its presence afterward is attributable to
// that run's swap and not a leftover from the other leg.
export function resetShipItCache(): void {
  rmSync(SHIPIT_DIR, { recursive: true, force: true });
}

// Squirrel.Mac's ShipIt helper performs the in-place swap and leaves its cache
// under ~/Library/Caches/<bundleId>.ShipIt, which is direct evidence the install
// went through Squirrel rather than anything the test did itself.
export function shipItEvidence(): { exists: boolean; entries: string[] } {
  try {
    return { exists: true, entries: readdirSync(SHIPIT_DIR) };
  } catch {
    return { exists: false, entries: [] };
  }
}

// The forge leg is "PostHog Code" pre-swap and "PostHog" post-swap, so match either name.
const APP_PROCESS_PATTERN = [FORGE_RUN_APP_BIN, RUN_APP_BIN]
  .map((bin) => path.basename(bin))
  .join("|");

export function isAppRunning(): boolean {
  try {
    execFileSync("pgrep", ["-x", APP_PROCESS_PATTERN], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

// Executable paths of the running main app processes (not helpers). Used to prove
// Squirrel's auto-relaunched process is running from the swapped bundle.
export function runningAppExecutables(): string[] {
  let pids: string[];
  try {
    pids = execFileSync("pgrep", ["-x", APP_PROCESS_PATTERN], {
      encoding: "utf8",
    })
      .trim()
      .split("\n")
      .filter(Boolean);
  } catch {
    return [];
  }
  return pids
    .map((pid) => {
      try {
        return execFileSync("ps", ["-p", pid, "-o", "comm="], {
          encoding: "utf8",
        }).trim();
      } catch {
        return "";
      }
    })
    .filter(Boolean);
}

export function killApp(): void {
  try {
    execFileSync("pkill", ["-x", APP_PROCESS_PATTERN]);
  } catch {
    // nothing running, fine
  }
}

export async function waitUntil(
  predicate: () => boolean | Promise<boolean>,
  timeoutMs: number,
  message: string,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Timed out after ${timeoutMs}ms: ${message}`);
}
