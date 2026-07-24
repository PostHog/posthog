import { execFileSync } from "node:child_process";
import path from "node:path";

const APP_TRANSLOCATION_SEGMENT = "AppTranslocation";
const MOUNT_READ_TIMEOUT_MS = 3000;

export type DarwinMountEntry = {
  mountPoint: string;
  options: string;
};

/**
 * Reads the Darwin mount table. Returns `null` when the table cannot be
 * obtained (e.g. `/sbin/mount` is missing, times out, or exits non-zero).
 */
export type ReadDarwinMountTable = () => string | null;

/** Parse `/sbin/mount` lines: `<device> on <mountPoint> (<opts>)` */
export function parseDarwinMountTable(output: string): DarwinMountEntry[] {
  const entries: DarwinMountEntry[] = [];
  for (const line of output.split("\n")) {
    const onMarker = line.indexOf(" on ");
    if (onMarker === -1) continue;
    const afterOn = line.slice(onMarker + 4);
    // `lastIndexOf` anchors to the trailing options block, so mount points
    // whose display names contain " (" (e.g. "/Volumes/My Backup (2)") still
    // parse correctly. The `line.endsWith(")")` check guarantees those parens
    // really are the options.
    const openParen = afterOn.lastIndexOf(" (");
    if (openParen === -1 || !line.endsWith(")")) continue;
    const mountPoint = afterOn.slice(0, openParen);
    const options = afterOn.slice(openParen + 2, -1);
    entries.push({ mountPoint, options });
  }
  return entries;
}

function mountOptionsImplyReadOnly(options: string): boolean {
  return options.toLowerCase().includes("read-only");
}

function longestMatchingMount(
  resolvedPath: string,
  entries: DarwinMountEntry[],
): DarwinMountEntry | null {
  let best: DarwinMountEntry | null = null;
  for (const e of entries) {
    const mp = e.mountPoint;
    // For `/` we'd otherwise build `//` which no real path starts with, so the
    // root mount would silently drop out of the comparison and the
    // `best.mountPoint === "/"` guard below would be unreachable.
    const under =
      resolvedPath === mp ||
      resolvedPath.startsWith(mp === "/" ? "/" : `${mp}/`);
    if (!under) continue;
    if (!best || mp.length > best.mountPoint.length) {
      best = e;
    }
  }
  return best;
}

/**
 * True when `resolvedAbsolutePath` sits on a **non-root** mount that `mount(8)`
 * reports as read-only (e.g. many DMGs, some external volumes).
 *
 * Ignores read-only `/` — on sealed macOS the system volume is read-only while
 * normal apps under /Applications or /Users still work.
 */
export function isMacosPathOnReadOnlyNonRootMountFromTable(
  resolvedAbsolutePath: string,
  mountTable: string,
): boolean {
  const normalized = path.resolve(resolvedAbsolutePath);
  const entries = parseDarwinMountTable(mountTable);
  const best = longestMatchingMount(normalized, entries);
  if (!best || best.mountPoint === "/") {
    return false;
  }
  return mountOptionsImplyReadOnly(best.options);
}

/**
 * Reads `/sbin/mount` synchronously. A short timeout keeps a hung NFS/SMB
 * share from freezing app startup — the exact failure mode this guard exists
 * to prevent. Returns `null` on any failure so callers can degrade to "don't
 * block".
 */
function readDarwinMountTableSync(): string | null {
  try {
    return execFileSync("/sbin/mount", {
      encoding: "utf8",
      maxBuffer: 10 * 1024 * 1024,
      timeout: MOUNT_READ_TIMEOUT_MS,
    });
  } catch {
    return null;
  }
}

/**
 * True when either path is under macOS App Translocation (read-only runtime).
 * Caller should gate on packaged darwin before using this to block startup.
 */
export function isMacosAppTranslocationPath(
  appPath: string,
  exePath: string,
): boolean {
  return (
    appPath.includes(APP_TRANSLOCATION_SEGMENT) ||
    exePath.includes(APP_TRANSLOCATION_SEGMENT)
  );
}

/**
 * Packaged macOS: translocated bundle path, or binary on a non-root read-only
 * mount (see mount(8)).
 *
 * `readMountTable` is injectable so tests can drive the mount-table branch
 * deterministically instead of relying on the host's real `/sbin/mount`.
 */
export function isMacosPackagedUnsafeBundleLocation(
  appPath: string,
  exePath: string,
  readMountTable: ReadDarwinMountTable = readDarwinMountTableSync,
): boolean {
  if (isMacosAppTranslocationPath(appPath, exePath)) {
    return true;
  }
  const table = readMountTable();
  if (table === null) {
    return false;
  }
  return isMacosPathOnReadOnlyNonRootMountFromTable(
    path.resolve(exePath),
    table,
  );
}
