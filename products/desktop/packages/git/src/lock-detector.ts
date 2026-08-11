import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export interface LockInfo {
  path: string;
  ageMs: number;
}

export async function getIndexLockPath(repoPath: string): Promise<string> {
  try {
    const { stdout } = await execFileAsync(
      "git",
      ["rev-parse", "--git-path", "index.lock"],
      { cwd: repoPath },
    );
    return path.resolve(repoPath, stdout.trim());
  } catch {
    return path.join(repoPath, ".git", "index.lock");
  }
}

export async function getLockInfo(repoPath: string): Promise<LockInfo | null> {
  const lockPath = await getIndexLockPath(repoPath);
  try {
    const stat = await fs.stat(lockPath);
    return {
      path: lockPath,
      ageMs: Date.now() - stat.mtimeMs,
    };
  } catch {
    return null;
  }
}

export async function removeLock(repoPath: string): Promise<void> {
  const lockPath = await getIndexLockPath(repoPath);
  await fs.rm(lockPath, { force: true });
}

export async function isLocked(repoPath: string): Promise<boolean> {
  return (await getLockInfo(repoPath)) !== null;
}

export async function waitForUnlock(
  repoPath: string,
  timeoutMs = 10000,
  intervalMs = 100,
): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (!(await isLocked(repoPath))) return true;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}
