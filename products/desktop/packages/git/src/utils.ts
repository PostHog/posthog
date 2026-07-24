// Namespace import (not `{ execFile }`) so modules that transitively reach this
// file stay bundle-safe for the renderer's browser build, where node builtins
// resolve to vite's `__vite-browser-external` stub (no named exports).
import * as childProcess from "node:child_process";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import gitUrlParse from "git-url-parse";

export type GitHubUrl =
  | { kind: "repo"; owner: string; repo: string }
  | { kind: "issue"; owner: string; repo: string; number: number }
  | { kind: "pr"; owner: string; repo: string; number: number };

export async function safeSymlink(
  source: string,
  target: string,
  type: "file" | "dir",
): Promise<boolean> {
  if (path.resolve(source) === path.resolve(target)) {
    return false;
  }

  const sourceDir = path.dirname(path.resolve(source));
  const targetDir = path.dirname(path.resolve(target));
  if (
    sourceDir === targetDir &&
    path.basename(source) === path.basename(target)
  ) {
    return false;
  }

  try {
    await fs.access(source);
  } catch {
    return false;
  }

  try {
    if (os.platform() === "win32") {
      // On Windows, skip symlinks entirely — they need admin/Developer Mode.
      // Use junctions for directories and hard links for files instead,
      // matching the approach used by pnpm, Deno, and npm.
      if (type === "dir") {
        await fs.symlink(source, target, "junction");
      } else {
        try {
          await fs.link(source, target);
        } catch {
          // Hard link can fail across drives — copy as last resort
          await fs.copyFile(source, target);
        }
      }
    } else {
      await fs.symlink(source, target, type);
    }
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      return false;
    }
    throw error;
  }
}

/**
 * copy file or directory, use copy-on-write, fall back to cp
 */
export async function clonePath(
  source: string,
  destination: string,
): Promise<boolean> {
  try {
    await fs.access(source);
  } catch {
    return false;
  }

  const parentDir = path.dirname(destination);
  await fs.mkdir(parentDir, { recursive: true });

  const platform = os.platform();

  try {
    if (platform === "darwin") {
      await execFileAsync("cp", ["-c", "-a", source, destination]);
    } else {
      await execFileAsync("cp", ["--reflink=auto", "-a", source, destination]);
    }
    return true;
  } catch {
    // CoW not supported, fall back to regular copy
  }

  await fs.cp(source, destination, { recursive: true });
  return true;
}

function execFileAsync(
  command: string,
  args: string[],
): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    childProcess.execFile(command, args, (error, stdout, stderr) => {
      if (error) {
        reject(error);
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

async function chmodTreeWritable(target: string): Promise<void> {
  let stat: import("node:fs").Stats;
  try {
    stat = await fs.lstat(target);
  } catch {
    return;
  }
  if (stat.isSymbolicLink()) return;
  try {
    await fs.chmod(target, stat.isDirectory() ? 0o700 : 0o600);
  } catch (error) {
    console.warn(`forceRemove: chmod failed on ${target}`, error);
  }
  if (!stat.isDirectory()) return;
  let entries: string[];
  try {
    entries = await fs.readdir(target);
  } catch (error) {
    console.warn(`forceRemove: readdir failed on ${target}`, error);
    return;
  }
  await Promise.all(
    entries.map((entry) => chmodTreeWritable(path.join(target, entry))),
  );
}

/**
 * Recursively remove a path, retrying after chmod'ing the tree writable when
 * the kernel rejects the initial removal with EACCES/EPERM. Worktrees commonly
 * contain read-only subtrees populated by Go's module cache (which marks every
 * cached directory mode 0555); plain `fs.rm` cannot unlink entries from those
 * parents until we restore the write bit.
 */
export async function forceRemove(target: string): Promise<void> {
  try {
    await fs.rm(target, { recursive: true, force: true, maxRetries: 3 });
    return;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== "EACCES" && code !== "EPERM") throw error;
  }
  await chmodTreeWritable(target);
  await fs.rm(target, { recursive: true, force: true, maxRetries: 3 });
}

export function parseGithubUrl(
  url: string | null | undefined,
): GitHubUrl | null {
  if (!url) return null;
  let parsed: gitUrlParse.GitUrl;
  try {
    parsed = gitUrlParse(url.trim());
  } catch {
    return null;
  }
  // git-url-parse normalizes source to github.com for any *.github.com host,
  // so check resource to reject api.github.com etc. SSH uses ssh.github.com.
  const resource = parsed.resource.toLowerCase();
  if (resource !== "github.com" && resource !== "ssh.github.com") return null;

  // Read pathname directly: git-url-parse keeps /pull/N in full_name but
  // strips /issues/N, and stuffs unknown path segments into owner. Pathname
  // is consistent across HTTPS, SSH, and shorthand inputs.
  const raw = parsed.pathname.split("/");
  if (raw[0] !== "") return null;
  const parts = raw[raw.length - 1] === "" ? raw.slice(1, -1) : raw.slice(1);
  if (parts.length < 2 || parts.some((p) => p === "")) return null;
  const [owner, repoRaw, segment, num] = parts;
  const repo = repoRaw.replace(/\.git$/, "");

  if (segment === "issues" || segment === "pull") {
    const number = Number(num);
    if (!Number.isInteger(number) || number <= 0) return null;
    return {
      kind: segment === "pull" ? "pr" : "issue",
      owner,
      repo,
      number,
    };
  }

  return { kind: "repo", owner, repo };
}
