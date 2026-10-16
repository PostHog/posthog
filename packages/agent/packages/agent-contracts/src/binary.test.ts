import { describe, expect, it } from "vitest";
import {
  ARCHIVE_EXTENSIONS,
  AUDIO_VIDEO_EXTENSIONS,
  BINARY_EXTENSIONS,
  DOCUMENT_BINARY_EXTENSIONS,
  EXECUTABLE_EXTENSIONS,
  FONT_EXTENSIONS,
  isBinaryFile,
} from "./binary";
import { IMAGE_MIME_TYPES } from "./image";

describe("isBinaryFile", () => {
  it.each([
    ["foo.png"],
    ["foo.JPG"],
    ["path/to/foo.gif"],
    ["foo.webp"],
    ["foo.tiff"],
    ["foo.avif"],
    ["foo.heic"],
    ["foo.heif"],
    ["foo.mp3"],
    ["foo.mp4"],
    ["foo.m4v"],
    ["foo.mov"],
    ["foo.flac"],
    ["foo.ogg"],
    ["foo.ogv"],
    ["foo.m4a"],
    ["foo.aac"],
    ["foo.mpg"],
    ["foo.mpeg"],
    ["foo.pdf"],
    ["foo.zip"],
    ["foo.tar.gz"],
    ["foo.tgz"],
    ["foo.bz2"],
    ["foo.xz"],
    ["foo.7z"],
    ["foo.exe"],
    ["foo.dll"],
    ["foo.dylib"],
    ["foo.wasm"],
    ["foo.bin"],
    ["foo.o"],
    ["foo.ttf"],
    ["foo.otf"],
    ["foo.woff2"],
    ["foo.eot"],
  ])("returns true for %s", (filename) => {
    expect(isBinaryFile(filename)).toBe(true);
  });

  it.each([
    ["foo.txt"],
    ["foo.md"],
    ["foo.ts"],
    ["foo.json"],
    ["foo"],
    [""],
    ["README"],
    [".gitignore"],
    ["foo.svg"],
    ["path/to/icon.svg"],
  ])("returns false for %s", (filename) => {
    expect(isBinaryFile(filename)).toBe(false);
  });

  it("excludes SVG so title generation reads it as text", () => {
    expect(BINARY_EXTENSIONS.has("svg")).toBe(false);
  });

  it("includes every binary extension from the source-of-truth sets", () => {
    const expected = [
      ...Object.keys(IMAGE_MIME_TYPES).filter((ext) => ext !== "svg"),
      ...AUDIO_VIDEO_EXTENSIONS,
      ...ARCHIVE_EXTENSIONS,
      ...EXECUTABLE_EXTENSIONS,
      ...FONT_EXTENSIONS,
      ...DOCUMENT_BINARY_EXTENSIONS,
    ];
    for (const ext of expected) {
      expect(BINARY_EXTENSIONS.has(ext)).toBe(true);
    }
  });
});
