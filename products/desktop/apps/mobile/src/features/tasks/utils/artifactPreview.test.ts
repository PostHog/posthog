import { describe, expect, it } from "vitest";
import {
  type ArtifactPreviewKind,
  artifactPreviewKind,
  artifactPreviewNeedsText,
  formatArtifactSize,
  formatJsonForPreview,
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
    ["payload.json", "json"],
    ["events.JSON", "json"],
    ["data.csv", "text"],
    ["rows.tsv", "text"],
    ["notes.txt", "text"],
    ["run.log", "text"],
    ["service.ts", "text"],
    ["Component.TSX", "text"],
    ["script.py", "text"],
    ["main.go", "text"],
    ["config.yaml", "text"],
    ["stream.jsonl", "text"],
    ["change.patch", "text"],
    ["archive.zip", "unsupported"],
    ["report.pdf", "unsupported"],
    ["noextension", "unsupported"],
    ["Dockerfile", "unsupported"],
    ["archive.tar.gz", "unsupported"],
    ["my.notes.md", "markdown"],
  ])("maps %s to %s", (fileName, expected) => {
    expect(artifactPreviewKind(fileName)).toBe(expected);
  });
});

describe("artifactPreviewNeedsText", () => {
  it.each<[ArtifactPreviewKind, boolean]>([
    ["markdown", true],
    ["html", true],
    ["json", true],
    ["text", true],
    ["image", false],
    ["unsupported", false],
  ])("returns %s -> %s", (kind, expected) => {
    expect(artifactPreviewNeedsText(kind)).toBe(expected);
  });
});

describe("formatJsonForPreview", () => {
  it("indents valid JSON", () => {
    expect(formatJsonForPreview('{"a":1,"b":[2]}')).toBe(
      '{\n  "a": 1,\n  "b": [\n    2\n  ]\n}',
    );
  });

  it.each<[string, string]>([
    ["not json at all", "not json at all"],
    ["{unterminated", "{unterminated"],
    ["", ""],
  ])("passes %s through unchanged", (raw, expected) => {
    expect(formatJsonForPreview(raw)).toBe(expected);
  });

  it("leaves oversized payloads untouched", () => {
    const raw = `{"a":"${"x".repeat(600_000)}"}`;
    expect(formatJsonForPreview(raw)).toBe(raw);
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
