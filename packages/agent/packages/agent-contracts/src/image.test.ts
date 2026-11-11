import { describe, expect, it } from "vitest";
import {
  buildImageDataUrl,
  getImageMimeType,
  isAllowedImageMimeType,
  isClaudeImageFile,
  isClaudeImageMimeType,
  isGifFile,
  isImageFile,
  isRasterImageFile,
  parseImageDataUrl,
} from "./image";

const TINY_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

describe("parseImageDataUrl", () => {
  it("parses a valid PNG data URL", () => {
    const result = parseImageDataUrl(
      `data:image/png;base64,${TINY_PNG_BASE64}`,
    );
    expect(result).toEqual({
      mimeType: "image/png",
      base64: TINY_PNG_BASE64,
    });
  });

  it.each([
    ["image/jpeg"],
    ["image/webp"],
    ["image/gif"],
    ["image/bmp"],
    ["image/avif"],
    ["image/tiff"],
    ["image/x-icon"],
  ])("accepts allowed mime type %s", (mimeType) => {
    const result = parseImageDataUrl(
      `data:${mimeType};base64,${TINY_PNG_BASE64}`,
    );
    expect(result).not.toBeNull();
    expect(result?.mimeType).toBe(mimeType);
  });

  it("rejects SVG data URLs to prevent script execution", () => {
    expect(
      parseImageDataUrl(`data:image/svg+xml;base64,${TINY_PNG_BASE64}`),
    ).toBeNull();
  });

  it.each([
    ["text/html"],
    ["application/javascript"],
    ["application/octet-stream"],
    ["text/plain"],
  ])("rejects non-image mime type %s", (mimeType) => {
    expect(
      parseImageDataUrl(`data:${mimeType};base64,${TINY_PNG_BASE64}`),
    ).toBeNull();
  });

  it("rejects non-base64 data URLs", () => {
    expect(parseImageDataUrl("data:image/png,not-base64")).toBeNull();
  });

  it.each([
    ["empty string", ""],
    ["plain text", "hello world"],
    ["http URL", "https://example.com/image.png"],
    ["truncated data prefix", "data"],
    ["missing payload separator", "data:image/png;base64"],
    ["empty payload", "data:image/png;base64,"],
    ["bare prefix", "data:"],
  ])("rejects non-data-URL or malformed input: %s", (_label, value) => {
    expect(parseImageDataUrl(value)).toBeNull();
  });

  it("rejects extremely large payloads", () => {
    const huge = "A".repeat(30 * 1024 * 1024);
    expect(parseImageDataUrl(`data:image/png;base64,${huge}`)).toBeNull();
  });

  it("trims surrounding whitespace before parsing", () => {
    const result = parseImageDataUrl(
      `\n  data:image/png;base64,${TINY_PNG_BASE64}  \n`,
    );
    expect(result?.mimeType).toBe("image/png");
  });

  it("tolerates long leading-whitespace prefixes", () => {
    const padding = " ".repeat(256);
    const result = parseImageDataUrl(
      `${padding}data:image/png;base64,${TINY_PNG_BASE64}`,
    );
    expect(result?.mimeType).toBe("image/png");
  });

  it("strips whitespace inside base64 payload", () => {
    const withNewlines = TINY_PNG_BASE64.match(/.{1,40}/g)?.join("\n") ?? "";
    const result = parseImageDataUrl(`data:image/png;base64,${withNewlines}`);
    expect(result?.base64).toBe(TINY_PNG_BASE64);
  });

  it("ignores additional parameters before the base64 marker", () => {
    const result = parseImageDataUrl(
      `data:image/png;charset=utf-8;base64,${TINY_PNG_BASE64}`,
    );
    expect(result?.mimeType).toBe("image/png");
  });

  it("normalises mime type casing", () => {
    const result = parseImageDataUrl(
      `data:IMAGE/PNG;base64,${TINY_PNG_BASE64}`,
    );
    expect(result?.mimeType).toBe("image/png");
  });

  it.each([[null], [undefined], [123], [{}]])(
    "handles non-string input safely: %p",
    (value) => {
      expect(parseImageDataUrl(value as unknown as string)).toBeNull();
    },
  );
});

describe("isAllowedImageMimeType", () => {
  it.each([["image/png"], ["IMAGE/JPEG"], ["image/webp"], ["image/gif"]])(
    "accepts %s",
    (mimeType) => {
      expect(isAllowedImageMimeType(mimeType)).toBe(true);
    },
  );

  it.each([
    ["image/svg+xml"],
    ["image/heic"],
    ["image/heif"],
    ["text/html"],
    ["application/javascript"],
    ["text/plain"],
  ])("rejects %s", (mimeType) => {
    expect(isAllowedImageMimeType(mimeType)).toBe(false);
  });
});

describe("buildImageDataUrl", () => {
  it("builds a data URL from parts", () => {
    expect(buildImageDataUrl("image/png", "abc")).toBe(
      "data:image/png;base64,abc",
    );
  });
});

describe("isImageFile", () => {
  it.each([
    ["foo.png"],
    ["foo.PNG"],
    ["path/to/foo.jpg"],
    ["foo.jpeg"],
    ["foo.gif"],
    ["foo.webp"],
    ["foo.bmp"],
    ["foo.ico"],
    ["foo.tiff"],
    ["foo.tif"],
    ["foo.svg"],
    ["foo.heic"],
    ["foo.heif"],
    ["foo.avif"],
  ])("returns true for %s", (filename) => {
    expect(isImageFile(filename)).toBe(true);
  });

  it.each([["foo.txt"], ["foo.md"], ["foo"], ["foo.ts"], ["foo.pdf"], [""]])(
    "returns false for %s",
    (filename) => {
      expect(isImageFile(filename)).toBe(false);
    },
  );
});

describe("isRasterImageFile", () => {
  it.each([
    ["foo.png"],
    ["foo.jpg"],
    ["foo.jpeg"],
    ["foo.JPEG"],
    ["foo.gif"],
    ["foo.webp"],
    ["foo.bmp"],
    ["foo.ico"],
    ["foo.tiff"],
    ["foo.tif"],
    ["foo.avif"],
  ])("returns true for raster %s", (filename) => {
    expect(isRasterImageFile(filename)).toBe(true);
  });

  it.each([["foo.svg"], ["foo.heic"], ["foo.heif"]])(
    "returns false for non-raster %s",
    (filename) => {
      expect(isRasterImageFile(filename)).toBe(false);
    },
  );

  it("returns false for non-images", () => {
    expect(isRasterImageFile("foo.txt")).toBe(false);
    expect(isRasterImageFile("foo")).toBe(false);
  });

  it("returns false for dotfiles with no real extension", () => {
    expect(isRasterImageFile(".gitignore")).toBe(false);
  });

  it("returns false for hidden files in a directory", () => {
    expect(isRasterImageFile("/path/.heic")).toBe(false);
    expect(isRasterImageFile("C:\\path\\.png")).toBe(false);
  });

  it("strips URI query and fragment before parsing extension", () => {
    expect(isRasterImageFile("ph://asset/IMG.png?width=1024")).toBe(true);
    expect(isRasterImageFile("file://photo.jpg#preview")).toBe(true);
  });
});

describe("isClaudeImageMimeType", () => {
  it.each([["image/jpeg"], ["image/png"], ["IMAGE/GIF"], ["image/webp"]])(
    "accepts %s",
    (mimeType) => {
      expect(isClaudeImageMimeType(mimeType)).toBe(true);
    },
  );

  it.each([
    ["image/svg+xml"],
    ["image/heic"],
    ["image/bmp"],
    ["image/avif"],
    ["application/octet-stream"],
    ["text/plain"],
  ])("rejects %s", (mimeType) => {
    expect(isClaudeImageMimeType(mimeType)).toBe(false);
  });
});

describe("isClaudeImageFile", () => {
  it.each([["foo.png"], ["foo.JPG"], ["foo.jpeg"], ["foo.gif"], ["foo.webp"]])(
    "returns true for Claude-supported %s",
    (filename) => {
      expect(isClaudeImageFile(filename)).toBe(true);
    },
  );

  it.each([
    ["foo.bmp"],
    ["foo.ico"],
    ["foo.tiff"],
    ["foo.svg"],
    ["foo.heic"],
    ["foo.heif"],
    ["foo.avif"],
    ["foo.txt"],
    ["foo"],
    [""],
  ])("returns false for unsupported %s", (filename) => {
    expect(isClaudeImageFile(filename)).toBe(false);
  });
});

describe("isGifFile", () => {
  it("returns true for .gif", () => {
    expect(isGifFile("foo.gif")).toBe(true);
    expect(isGifFile("foo.GIF")).toBe(true);
  });

  it("returns false for non-gif images", () => {
    expect(isGifFile("foo.png")).toBe(false);
  });
});

describe("getImageMimeType", () => {
  it.each([
    ["foo.png", "image/png"],
    ["foo.jpg", "image/jpeg"],
    ["foo.JPEG", "image/jpeg"],
    ["foo.gif", "image/gif"],
    ["foo.webp", "image/webp"],
    ["foo.svg", "image/svg+xml"],
    ["foo.heic", "image/heic"],
    ["foo.heif", "image/heif"],
    ["foo.avif", "image/avif"],
    ["foo.ico", "image/x-icon"],
    ["foo.tiff", "image/tiff"],
    ["foo.tif", "image/tiff"],
  ])("maps %s to %s", (filename, expected) => {
    expect(getImageMimeType(filename)).toBe(expected);
  });

  it("falls back to application/octet-stream for unknown extensions", () => {
    expect(getImageMimeType("foo.unknown")).toBe("application/octet-stream");
    expect(getImageMimeType("foo")).toBe("application/octet-stream");
  });

  it("strips URI query and fragment from picker-style URIs", () => {
    expect(getImageMimeType("ph://asset/IMG.png?width=1024")).toBe("image/png");
    expect(getImageMimeType("https://cdn/img.webp#thumb")).toBe("image/webp");
  });

  it("ignores extensions on hidden basenames", () => {
    expect(getImageMimeType("/path/.heic")).toBe("application/octet-stream");
  });
});
