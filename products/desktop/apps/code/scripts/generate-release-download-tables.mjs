#!/usr/bin/env node
// Renders the "Downloads" section appended to GitHub release notes: one
// markdown table per OS with a direct download link, blockmap link, and
// SHA-256 per installer. Input is a directory of sha256sum/shasum output
// files collected from the publish jobs in code-release.yml — the asset
// patterns below must cover every file those jobs checksum.
import { readdirSync, readFileSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const DOWNLOAD_BASE = "https://github.com/PostHog/code/releases/download";

const ASSET_KINDS = [
  { pattern: /-mac\.dmg$/, os: "macos", pkg: "DMG", pkgOrder: 0 },
  { pattern: /-mac\.zip$/, os: "macos", pkg: "ZIP", pkgOrder: 1 },
  {
    pattern: /-win\.exe$/,
    os: "windows",
    pkg: "Installer (.exe)",
    pkgOrder: 0,
  },
  { pattern: /\.AppImage$/, os: "linux", pkg: "AppImage", pkgOrder: 0 },
  { pattern: /\.deb$/, os: "linux", pkg: "Debian (.deb)", pkgOrder: 1 },
  { pattern: /\.rpm$/, os: "linux", pkg: "RPM (.rpm)", pkgOrder: 2 },
];

const OS_SECTIONS = [
  // macOS sorts by arch first: users pick their chip, then a format.
  // Linux sorts by package first: the distro dictates deb/rpm/AppImage.
  {
    os: "macos",
    heading: "macOS",
    archOrder: ["arm64", "x64"],
    archFirst: true,
  },
  {
    os: "windows",
    heading: "Windows",
    archOrder: ["x64", "arm64"],
    archFirst: false,
  },
  {
    os: "linux",
    heading: "Linux",
    archOrder: ["x64", "arm64"],
    archFirst: false,
  },
];

const ARCH_LABELS = {
  macos: { arm64: "Apple Silicon (arm64)", x64: "Intel (x64)" },
  windows: { arm64: "arm64", x64: "x64" },
  linux: { arm64: "arm64", x64: "x64" },
};

// Parses `sha256sum`/`shasum -a 256` output into a filename -> sha map.
export function parseChecksums(text) {
  const checksums = new Map();
  for (const line of text.split("\n")) {
    const match = line.trim().match(/^([0-9a-f]{64})[ *]+(.+)$/);
    if (match) checksums.set(match[2], match[1]);
  }
  return checksums;
}

function detectArch(name) {
  if (/aarch64|arm64/.test(name)) return "arm64";
  if (/x86_64|amd64|x64/.test(name)) return "x64";
  return "unknown";
}

export function buildDownloadTables(version, checksums) {
  const base = `${DOWNLOAD_BASE}/v${version.replace(/^v/, "")}`;
  const rows = { macos: [], windows: [], linux: [] };

  for (const [name, sha] of checksums) {
    if (name.endsWith(".blockmap")) continue;
    const kind = ASSET_KINDS.find((k) => k.pattern.test(name));
    if (!kind) continue;
    const arch = detectArch(name);
    const blockmapName = `${name}.blockmap`;
    const blockmap = checksums.has(blockmapName)
      ? `[blockmap](${base}/${blockmapName})`
      : "—";
    rows[kind.os].push({
      name,
      arch,
      pkgOrder: kind.pkgOrder,
      cells: [
        kind.pkg,
        ARCH_LABELS[kind.os][arch] ?? arch,
        `[${name}](${base}/${name})`,
        blockmap,
        // Abbreviated sha; the link title shows the full hash on hover.
        `[\`${sha.slice(0, 6)}\`](${base}/${name} "${sha}")`,
      ],
    });
  }

  const sections = [];
  for (const { os, heading, archOrder, archFirst } of OS_SECTIONS) {
    if (rows[os].length === 0) continue;
    const archRank = (row) => {
      const rank = archOrder.indexOf(row.arch);
      return rank === -1 ? archOrder.length : rank;
    };
    rows[os].sort((a, b) => {
      const aKey = archFirst
        ? [archRank(a), a.pkgOrder]
        : [a.pkgOrder, archRank(a)];
      const bKey = archFirst
        ? [archRank(b), b.pkgOrder]
        : [b.pkgOrder, archRank(b)];
      return (
        aKey[0] - bKey[0] || aKey[1] - bKey[1] || a.name.localeCompare(b.name)
      );
    });
    sections.push(
      [
        `### ${heading}`,
        "",
        "| Package | Architecture | Download | Blockmap | SHA-256 |",
        "| --- | --- | --- | --- | --- |",
        ...rows[os].map((row) => `| ${row.cells.join(" | ")} |`),
      ].join("\n"),
    );
  }

  if (sections.length === 0) return "";
  return `## Downloads\n\n${sections.join("\n\n")}\n`;
}

function main() {
  const [, , version, checksumsDir] = process.argv;

  if (!version || !checksumsDir) {
    console.error(
      "Usage: generate-release-download-tables.mjs <version> <checksums-dir>",
    );
    process.exit(1);
  }

  const files = readdirSync(checksumsDir)
    .filter((name) => name.endsWith(".txt"))
    .sort();
  const text = files
    .map((name) => readFileSync(join(checksumsDir, name), "utf8"))
    .join("\n");
  const checksums = parseChecksums(text);

  for (const name of checksums.keys()) {
    if (
      !name.endsWith(".blockmap") &&
      !ASSET_KINDS.some((kind) => kind.pattern.test(name))
    ) {
      console.error(`Skipping unrecognized artifact: ${name}`);
    }
  }

  const markdown = buildDownloadTables(version, checksums);
  if (!markdown) {
    console.error(`No release artifacts found in ${checksumsDir}`);
    process.exit(1);
  }
  process.stdout.write(markdown);
}

if (
  process.argv[1] &&
  realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
