#!/usr/bin/env node
import { realpathSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const RELEASES_API_URL =
  "https://api.github.com/repos/PostHog/code/releases?per_page=30";

export function toFeedReleases(apiReleases) {
  return apiReleases
    .filter((release) => !release.draft)
    .map((release) => ({
      version: release.tag_name.replace(/^v/, ""),
      name:
        release.name && release.name.length > 0
          ? release.name
          : release.tag_name,
      notes: release.body ?? "",
      date: release.published_at,
      isPrerelease: release.prerelease,
      htmlUrl: release.html_url,
    }));
}

async function main() {
  const [, , outputPath] = process.argv;

  if (!outputPath) {
    console.error("Usage: build-releases-feed.mjs <output-json>");
    process.exit(1);
  }

  const headers = { Accept: "application/vnd.github+json" };
  if (process.env.GH_TOKEN) {
    headers.Authorization = `Bearer ${process.env.GH_TOKEN}`;
  }

  const response = await fetch(RELEASES_API_URL, { headers });
  if (!response.ok) {
    throw new Error(`GitHub releases fetch failed: ${response.status}`);
  }

  const releases = toFeedReleases(await response.json());
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
