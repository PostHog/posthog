import { describe, expect, it } from "vitest";
import {
  buildDownloadTables,
  parseChecksums,
} from "./generate-release-download-tables.mjs";

const sha = (seed) => seed.repeat(64).slice(0, 64);

// Asset names as produced by a real release (v0.56.90).
const releaseChecksums = () =>
  new Map(
    [
      "PostHog-Desktop-0.56.90-arm64-mac.dmg",
      "PostHog-Desktop-0.56.90-arm64-mac.dmg.blockmap",
      "PostHog-Desktop-0.56.90-arm64-mac.zip",
      "PostHog-Desktop-0.56.90-arm64-mac.zip.blockmap",
      "PostHog-Desktop-0.56.90-x64-mac.dmg",
      "PostHog-Desktop-0.56.90-x64-mac.dmg.blockmap",
      "PostHog-Desktop-0.56.90-x64-mac.zip",
      "PostHog-Desktop-0.56.90-x64-mac.zip.blockmap",
      "PostHog-Desktop-0.56.90-x64-win.exe",
      "PostHog-Desktop-0.56.90-x64-win.exe.blockmap",
      "PostHog-Desktop-0.56.90-x86_64-linux.AppImage",
      "PostHog-Desktop-0.56.90-arm64-linux.AppImage",
      "PostHog-Desktop-0.56.90-amd64-linux.deb",
      "PostHog-Desktop-0.56.90-arm64-linux.deb",
      "PostHog-Desktop-0.56.90-x86_64-linux.rpm",
      "PostHog-Desktop-0.56.90-aarch64-linux.rpm",
    ].map((name, index) => [name, sha(`${index % 10}`)]),
  );

const tableRows = (markdown) =>
  markdown
    .split("\n")
    .filter(
      (line) =>
        line.startsWith("| ") &&
        !line.startsWith("| Package") &&
        !line.startsWith("| ---"),
    );

// Cell 2 of `| Package | Architecture | Download | ... |` split on " | ".
const downloadCells = (markdown) =>
  tableRows(markdown).map((line) => line.split(" | ")[2]);

describe("parseChecksums", () => {
  it.each([
    [
      "sha256sum text mode (two spaces)",
      `${sha("a")}  PostHog-Desktop-1.2.3-arm64-mac.dmg`,
      "PostHog-Desktop-1.2.3-arm64-mac.dmg",
      sha("a"),
    ],
    [
      "shasum binary mode (space + asterisk)",
      `${sha("b")} *PostHog-Desktop-1.2.3-x64-win.exe`,
      "PostHog-Desktop-1.2.3-x64-win.exe",
      sha("b"),
    ],
  ])("parses %s output, ignoring other lines", (_label, line, name, hash) => {
    const text = [line, "not a checksum line", ""].join("\n");

    const checksums = parseChecksums(text);

    expect(checksums.get(name)).toBe(hash);
    expect(checksums.size).toBe(1);
  });
});

describe("buildDownloadTables", () => {
  it("renders one section per OS, in macOS/Windows/Linux order", () => {
    const markdown = buildDownloadTables(releaseChecksums());

    const headings = markdown
      .split("\n")
      .filter((line) => line.startsWith("#"));
    expect(headings).toEqual([
      "## Downloads",
      "### macOS",
      "### Windows",
      "### Linux",
    ]);
  });

  it("orders macOS by arch (Apple Silicon first) and Linux by package", () => {
    const markdown = buildDownloadTables(releaseChecksums());

    expect(downloadCells(markdown)).toEqual([
      "[PostHog-Desktop-0.56.90-arm64-mac.dmg](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-arm64-mac.dmg)",
      "[PostHog-Desktop-0.56.90-arm64-mac.zip](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-arm64-mac.zip)",
      "[PostHog-Desktop-0.56.90-x64-mac.dmg](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-x64-mac.dmg)",
      "[PostHog-Desktop-0.56.90-x64-mac.zip](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-x64-mac.zip)",
      "[PostHog-Desktop-0.56.90-x64-win.exe](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-x64-win.exe)",
      "[PostHog-Desktop-0.56.90-x86_64-linux.AppImage](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-x86_64-linux.AppImage)",
      "[PostHog-Desktop-0.56.90-arm64-linux.AppImage](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-arm64-linux.AppImage)",
      "[PostHog-Desktop-0.56.90-amd64-linux.deb](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-amd64-linux.deb)",
      "[PostHog-Desktop-0.56.90-arm64-linux.deb](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-arm64-linux.deb)",
      "[PostHog-Desktop-0.56.90-x86_64-linux.rpm](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-x86_64-linux.rpm)",
      "[PostHog-Desktop-0.56.90-aarch64-linux.rpm](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-aarch64-linux.rpm)",
    ]);
  });

  it.each([
    [
      "links the blockmap when present",
      "arm64-mac.dmg](",
      "[blockmap](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-arm64-mac.dmg.blockmap)",
    ],
    ["shows a dash when the blockmap is absent", "amd64-linux.deb](", "| — |"],
  ])("%s", (_label, rowFragment, expected) => {
    const rows = tableRows(buildDownloadTables(releaseChecksums()));

    const row = rows.find((line) => line.includes(rowFragment));
    expect(row).toContain(expected);
  });

  it("abbreviates the sha to 6 digits with the full hash as hover tooltip", () => {
    const checksums = releaseChecksums();
    const markdown = buildDownloadTables(checksums);
    const exeRow = markdown
      .split("\n")
      .find((line) => line.includes("x64-win.exe]("));
    const fullSha = checksums.get("PostHog-Desktop-0.56.90-x64-win.exe");

    expect(exeRow).toContain(
      `[\`${fullSha.slice(0, 6)}\`](https://desktop-releases.posthog.com/stable/PostHog-Desktop-0.56.90-x64-win.exe "${fullSha}")`,
    );
    expect(exeRow).not.toContain(`\`${fullSha}\``);
  });

  it("does not render blockmaps or unrecognized files as rows", () => {
    const checksums = releaseChecksums();
    checksums.set("latest-mac.yml", sha("c"));
    const markdown = buildDownloadTables(checksums);

    expect(markdown).not.toContain("latest-mac.yml");
    expect(markdown).not.toContain(
      "[PostHog-Desktop-0.56.90-arm64-mac.dmg.blockmap](",
    );
  });

  it("labels macOS architectures and skips empty sections", () => {
    const macOnly = new Map([
      ["PostHog-Desktop-1.2.3-arm64-mac.dmg", sha("a")],
      ["PostHog-Desktop-1.2.3-x64-mac.dmg", sha("b")],
    ]);

    const markdown = buildDownloadTables(macOnly);

    expect(markdown).toContain("Apple Silicon (arm64)");
    expect(markdown).toContain("Intel (x64)");
    expect(markdown).not.toContain("### Windows");
    expect(markdown).not.toContain("### Linux");
  });

  it("returns an empty string when there are no recognized artifacts", () => {
    expect(buildDownloadTables(new Map())).toBe("");
  });
});
