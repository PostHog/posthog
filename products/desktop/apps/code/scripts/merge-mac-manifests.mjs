#!/usr/bin/env node
import { readFileSync, realpathSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse, stringify } from "yaml";

export function mergeManifests(arm64, x64) {
  if (arm64.version !== x64.version) {
    throw new Error(
      `Manifest version mismatch: arm64=${arm64.version} x64=${x64.version}`,
    );
  }

  const seenUrls = new Set();
  const mergedFiles = [];
  for (const file of [...arm64.files, ...x64.files]) {
    if (!seenUrls.has(file.url)) {
      seenUrls.add(file.url);
      mergedFiles.push(file);
    }
  }

  const { path: _path, sha512: _sha512, size: _size, ...rest } = arm64;
  return { ...rest, files: mergedFiles };
}

function main() {
  const [, , arm64Path, x64Path, outputPath] = process.argv;

  if (!arm64Path || !x64Path || !outputPath) {
    console.error(
      "Usage: merge-mac-manifests.mjs <arm64-yml> <x64-yml> <output-yml>",
    );
    process.exit(1);
  }

  const arm64 = parse(readFileSync(arm64Path, "utf8"));
  const x64 = parse(readFileSync(x64Path, "utf8"));
  const merged = mergeManifests(arm64, x64);

  writeFileSync(outputPath, stringify(merged), "utf8");
  console.log(
    `Merged ${merged.files.length} files from arm64+x64 manifests -> ${outputPath}`,
  );
}

if (
  process.argv[1] &&
  realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
