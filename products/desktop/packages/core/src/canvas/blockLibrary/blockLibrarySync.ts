import {
  BLOCK_ICONS_PATH,
  BLOCK_RUNTIME_PATH,
  BLOCKS_DIR,
} from "./blockDefinitions";
import { BLOCK_COMPONENT_SOURCES } from "./componentSources";
import { BLOCK_ICONS_SOURCE } from "./iconsSource";
import { BLOCK_RUNTIME_SOURCE } from "./runtimeSource";

export type LibraryFiles = Record<string, string>;

export const BLOCK_MANIFEST_PATH = `${BLOCKS_DIR}/library.json`;

function librarySource(path: string): string | undefined {
  if (path === BLOCK_RUNTIME_PATH) return BLOCK_RUNTIME_SOURCE;
  if (path === BLOCK_ICONS_PATH) return BLOCK_ICONS_SOURCE;
  const match = new RegExp(`^${BLOCKS_DIR}/([A-Za-z0-9]+)\\.tsx$`).exec(path);
  return match?.[1] ? BLOCK_COMPONENT_SOURCES[match[1]] : undefined;
}

export function hashText(text: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function readManifest(files: LibraryFiles): Record<string, string> {
  const raw = files[BLOCK_MANIFEST_PATH];
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    );
  } catch {
    return {};
  }
}

function writeManifest(
  files: LibraryFiles,
  manifest: Record<string, string>,
): LibraryFiles {
  const sorted = Object.fromEntries(
    Object.entries(manifest).sort(([a], [b]) => a.localeCompare(b)),
  );
  return {
    ...files,
    [BLOCK_MANIFEST_PATH]: `${JSON.stringify(sorted, null, 2)}\n`,
  };
}

export function withLibraryFile(
  files: LibraryFiles,
  path: string,
): LibraryFiles {
  const source = librarySource(path);
  if (files[path] !== undefined || source === undefined) return files;
  return writeManifest(
    { ...files, [path]: source },
    { ...readManifest(files), [path]: hashText(source) },
  );
}

export function syncBlockLibrary(input: LibraryFiles): LibraryFiles {
  const files =
    input[BLOCK_RUNTIME_PATH] !== undefined
      ? withLibraryFile(input, BLOCK_ICONS_PATH)
      : input;
  const manifest = readManifest(files);
  const isUntouched = (path: string) =>
    files[path] !== undefined && hashText(files[path]) === manifest[path];
  const sharedEdited = [BLOCK_RUNTIME_PATH, BLOCK_ICONS_PATH].some(
    (path) => files[path] !== undefined && !isUntouched(path),
  );
  if (sharedEdited) return files;
  let next = files;
  let changed = false;
  for (const [path, copiedHash] of Object.entries(manifest)) {
    const current = files[path];
    const latest = librarySource(path);
    const untouched = current !== undefined && hashText(current) === copiedHash;
    if (!untouched || latest === undefined || latest === current) continue;
    next = { ...next, [path]: latest };
    manifest[path] = hashText(latest);
    changed = true;
  }
  return changed ? writeManifest(next, manifest) : files;
}
