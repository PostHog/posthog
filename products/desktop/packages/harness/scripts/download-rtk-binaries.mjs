#!/usr/bin/env node

import { existsSync } from "node:fs";
import { chmod, mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { unzipSync } from "fflate";
import { extract } from "tar";
import {
  RTK_RELEASE_ASSETS,
  rtkReleaseUrl,
} from "../src/extensions/rtk/targets.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const destination =
  process.argv[2] ?? join(__dirname, "..", "dist", "extensions", "rtk", "bin");

async function download(asset) {
  const targetDirectory = join(destination, asset.target);
  const executable = join(
    targetDirectory,
    asset.target.includes("windows") ? "rtk.exe" : "rtk",
  );
  if (existsSync(executable)) {
    return;
  }

  const response = await fetch(rtkReleaseUrl(asset));
  if (!response.ok) {
    throw new Error(`Failed to download ${asset.archive}: ${response.status}`);
  }

  const content = Buffer.from(await response.arrayBuffer());
  await mkdir(targetDirectory, { recursive: true });
  if (asset.archive.endsWith(".zip")) {
    const entries = unzipSync(content);
    const binary = entries["rtk.exe"];
    if (!binary) {
      throw new Error(`Missing rtk.exe in ${asset.archive}`);
    }
    await writeFile(executable, binary);
    return;
  }

  const archivePath = join(targetDirectory, asset.archive);
  await writeFile(archivePath, content);
  await extract({ file: archivePath, cwd: targetDirectory });
  await rm(archivePath);
  await chmod(executable, 0o755);
}

await Promise.all(RTK_RELEASE_ASSETS.map(download));
