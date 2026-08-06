#!/usr/bin/env node
import { realpathSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const RELEASES_API_URL =
  "https://api.github.com/repos/PostHog/posthog/releases";
const MAX_RELEASES = 30;
const PAGE_SIZE = 100;
const DESKTOP_TAG_PATTERN = /^desktop-v\d+\.\d+\.\d+$/;

export function toFeedReleases(apiReleases) {
  return apiReleases
    .filter(
      (release) => !release.draft && DESKTOP_TAG_PATTERN.test(release.tag_name),
    )
    .map((release) => ({
      version: release.tag_name.replace(/^desktop-v/, ""),
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

export async function fetchDesktopReleases(fetchImpl = fetch) {
  const headers = { Accept: "application/vnd.github+json" };
  if (process.env.GH_TOKEN) {
    headers.Authorization = `Bearer ${process.env.GH_TOKEN}`;
  }

  const releases = [];
  for (let page = 1; releases.length < MAX_RELEASES; page++) {
    const url = `${RELEASES_API_URL}?per_page=${PAGE_SIZE}&page=${page}`;
    const response = await fetchImpl(url, { headers });
    if (!response.ok) {
      throw new Error(`GitHub releases fetch failed: ${response.status}`);
    }

    const apiReleases = await response.json();
    releases.push(...toFeedReleases(apiReleases));
    if (apiReleases.length < PAGE_SIZE) break;
  }

  return releases.slice(0, MAX_RELEASES);
}

async function main() {
  const [, , outputPath] = process.argv;

  if (!outputPath) {
    console.error("Usage: build-releases-feed.mjs <output-json>");
    process.exit(1);
  }

  const releases = await fetchDesktopReleases();
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
