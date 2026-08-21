import { describe, expect, it } from "vitest";
import {
  type ArtifactPreviewKind,
  artifactPreviewKind,
  formatArtifactSize,
} from "./artifactPreview";

describe("artifactPreviewKind", () => {
  it.each<[string, ArtifactPreviewKind]>([
    ["chart.png", "image"],
    ["photo.JPEG", "image"],
    ["diagram.webp", "image"],
    ["report.md", "markdown"],
    ["notes.markdown", "markdown"],
    ["doc.MDX", "markdown"],
    ["page.html", "html"],
    ["page.htm", "html"],
    ["data.csv", "unsupported"],
    ["archive.zip", "unsupported"],
    ["noextension", "unsupported"],
  ])("maps %s to %s", (fileName, expected) => {
    expect(artifactPreviewKind(fileName)).toBe(expected);
  });
});

describe("formatArtifactSize", () => {
  it.each<[number | undefined, string | null]>([
    [undefined, null],
    [0, "0 B"],
    [512, "512 B"],
    [1_500, "2 KB"],
    [2_400_000, "2.4 MB"],
  ])("formats %s as %s", (size, expected) => {
    expect(formatArtifactSize(size)).toBe(expected);
  });
});
