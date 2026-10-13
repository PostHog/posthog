import {
  cp,
  lstat,
  mkdir,
  readdir,
  readlink,
  rename,
  rm,
  symlink,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";

interface PersistentDirectory {
  source: string;
  target: string;
}

function isMissingPathError(error: unknown): boolean {
  return (
    error instanceof Error &&
    "code" in error &&
    (error as NodeJS.ErrnoException).code === "ENOENT"
  );
}

function isCrossDeviceError(error: unknown): boolean {
  return (
    error instanceof Error &&
    "code" in error &&
    (error as NodeJS.ErrnoException).code === "EXDEV"
  );
}

async function migrateExistingDirectory(
  source: string,
  target: string,
): Promise<void> {
  const sourceEntries = await readdir(source);
  const targetEntries = await readdir(target);
  if (sourceEntries.length === 0) {
    await rm(source, { recursive: true, force: true });
    return;
  }
  if (targetEntries.length > 0) {
    throw new Error(
      `Cannot migrate persistent agent state from ${source}: ${target} is not empty`,
    );
  }

  await rm(target, { recursive: true, force: true });
  try {
    await rename(source, target);
  } catch (error) {
    if (!isCrossDeviceError(error)) throw error;
    await cp(source, target, {
      recursive: true,
      errorOnExist: true,
      force: false,
    });
    await rm(source, { recursive: true, force: true });
  }
}

async function linkPersistentDirectory({
  source,
  target,
}: PersistentDirectory): Promise<void> {
  const resolvedSource = path.resolve(source);
  const resolvedTarget = path.resolve(target);
  if (resolvedSource === resolvedTarget) return;

  await mkdir(resolvedTarget, { recursive: true });
  await mkdir(path.dirname(resolvedSource), { recursive: true });

  try {
    const sourceStats = await lstat(resolvedSource);
    if (sourceStats.isSymbolicLink()) {
      const currentTarget = path.resolve(
        path.dirname(resolvedSource),
        await readlink(resolvedSource),
      );
      if (currentTarget === resolvedTarget) return;
      await rm(resolvedSource, { force: true });
    } else if (sourceStats.isDirectory()) {
      await migrateExistingDirectory(resolvedSource, resolvedTarget);
    } else {
      throw new Error(
        `Persistent agent state source must be a directory: ${resolvedSource}`,
      );
    }
  } catch (error) {
    if (!isMissingPathError(error)) throw error;
  }

  await symlink(resolvedTarget, resolvedSource, "dir");
}

export async function configurePersistentAgentState(
  stateRoot: string,
  homeDir: string = os.homedir(),
): Promise<void> {
  if (!path.isAbsolute(stateRoot)) {
    throw new Error("Persistent agent state root must be an absolute path");
  }

  const claudeConfigDir =
    process.env.CLAUDE_CONFIG_DIR || path.join(homeDir, ".claude");
  const codexHome = process.env.CODEX_HOME || path.join(homeDir, ".codex");
  const directories: PersistentDirectory[] = [
    {
      source: path.join(claudeConfigDir, "projects"),
      target: path.join(stateRoot, "claude", "projects"),
    },
    {
      source: path.join(claudeConfigDir, "session-env"),
      target: path.join(stateRoot, "claude", "session-env"),
    },
    {
      source: path.join(claudeConfigDir, "plans"),
      target: path.join(stateRoot, "claude", "plans"),
    },
    {
      source: path.join(claudeConfigDir, "todos"),
      target: path.join(stateRoot, "claude", "todos"),
    },
    {
      source: path.join(codexHome, "sessions"),
      target: path.join(stateRoot, "codex", "sessions"),
    },
    {
      source: path.join(codexHome, "shell_snapshots"),
      target: path.join(stateRoot, "codex", "shell_snapshots"),
    },
  ];

  // Avoid leaving other mappings mutating after one setup operation fails.
  for (const directory of directories) {
    await linkPersistentDirectory(directory);
  }
}
