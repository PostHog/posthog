#!/usr/bin/env node
import { readFileSync, realpathSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const FEED_URL = "https://desktop-releases.posthog.com/stable/releases.json";
const MAX_RELEASES = 30;

export function mergeRelease(existingReleases, entry) {
  return [
    entry,
    ...existingReleases.filter((release) => release.version !== entry.version),
  ].slice(0, MAX_RELEASES);
}

export async function fetchExistingReleases(fetchImpl = fetch) {
  const response = await fetchImpl(FEED_URL, {
    headers: { Accept: "application/json" },
  });
  // A feed that has never been published surfaces as 403/404 from CloudFront.
  if (response.status === 403 || response.status === 404) {
    console.warn(
      `Release feed fetch returned ${response.status}; starting an empty feed`,
    );
    return [];
  }
  if (!response.ok) {
    throw new Error(`Release feed fetch failed: ${response.status}`);
  }
  const data = await response.json();
  if (!Array.isArray(data?.releases)) {
    // Rebuilding from an empty base would wipe the published history.
    throw new Error("Release feed response has no releases array");
  }
  return data.releases;
}

async function main() {
  const [, , version, notesPath, outputPath] = process.argv;

  if (!version || !notesPath || !outputPath) {
    console.error(
      "Usage: build-releases-feed.mjs <version> <notes-file> <output-json>",
    );
    process.exit(1);
  }

  const releases = mergeRelease(await fetchExistingReleases(), {
    version,
    name: `v${version}`,
    notes: readFileSync(notesPath, "utf8"),
    date: new Date().toISOString(),
    isPrerelease: false,
    htmlUrl: `https://github.com/PostHog/posthog/releases/tag/desktop-v${version}`,
  });
  writeFileSync(
    outputPath,
    `${JSON.stringify({ releases }, null, 2)}\n`,
    "utf8",
  );
  console.log(`Wrote ${releases.length} releases -> ${outputPath}`);
}

if (
  process.argv[1] &&
  realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  await main();
}
