#!/usr/bin/env node
import { readFileSync, realpathSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse, stringify } from "yaml";

export function withReleaseNotes(manifest, notes) {
  return { ...manifest, releaseNotes: notes };
}

function main() {
  const [, , notesPath, ...manifestPaths] = process.argv;

  if (!notesPath || manifestPaths.length === 0) {
    console.error(
      "Usage: inject-release-notes.mjs <notes-md> <channel-yml> [...channel-yml]",
    );
    process.exit(1);
  }

  const notes = readFileSync(notesPath, "utf8").trim();
  for (const manifestPath of manifestPaths) {
    const manifest = parse(readFileSync(manifestPath, "utf8"));
    writeFileSync(
      manifestPath,
      stringify(withReleaseNotes(manifest, notes)),
      "utf8",
    );
    console.log(`Injected release notes -> ${manifestPath}`);
  }
}

if (
  process.argv[1] &&
  realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
