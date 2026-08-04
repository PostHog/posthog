import { beforeEach, describe, expect, it, vi } from "vitest";

const mockSaveClipboardImage = vi.hoisted(() => vi.fn());
const mockSaveClipboardText = vi.hoisted(() => vi.fn());
const mockSaveClipboardFile = vi.hoisted(() => vi.fn());
const mockDownscaleImageFile = vi.hoisted(() => vi.fn());

vi.mock("@posthog/shared", async () => {
  const actual =
    await vi.importActual<typeof import("@posthog/shared")>("@posthog/shared");
  return { ...actual, getImageMimeType: () => "image/png" };
});

import {
  arrayBufferToBase64,
  type FilePersistHost,
  persistBrowserFile,
  persistImageFile,
  persistImageFilePath,
  persistTextContent,
  resolveDroppedFile,
} from "./persistFile";

const host: FilePersistHost = {
  saveClipboardImage: mockSaveClipboardImage,
  saveClipboardText: mockSaveClipboardText,
  saveClipboardFile: mockSaveClipboardFile,
  downscaleImageFile: mockDownscaleImageFile,
};

describe("arrayBufferToBase64", () => {
  it("encodes bytes to base64", () => {
    const buffer = new TextEncoder().encode("hello").buffer;
    expect(arrayBufferToBase64(buffer)).toBe(btoa("hello"));
  });
});

describe("persistFile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("passes original text filenames through clipboard persistence", async () => {
    mockSaveClipboardText.mockResolvedValue({
      path: "/tmp/posthog-code-clipboard/attachment-123/notes.md",
      name: "notes.md",
    });

    const result = await persistTextContent(host, "# hello", "notes.md");

    expect(mockSaveClipboardText).toHaveBeenCalledWith({
      text: "# hello",
      originalName: "notes.md",
    });
    expect(result).toEqual({
      path: "/tmp/posthog-code-clipboard/attachment-123/notes.md",
      name: "notes.md",
    });
  });

  it("persists image files via saveClipboardImage", async () => {
    mockSaveClipboardImage.mockResolvedValue({
      path: "/tmp/posthog-code-clipboard/attachment-789/photo.png",
      name: "photo.png",
      mimeType: "image/png",
    });

    const file = {
      name: "photo.png",
      type: "image/png",
      arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
    } as unknown as File;

    const result = await persistImageFile(host, file);

    expect(mockSaveClipboardImage).toHaveBeenCalledWith(
      expect.objectContaining({
        mimeType: "image/png",
        originalName: "photo.png",
      }),
    );
    expect(result).toEqual({
      path: "/tmp/posthog-code-clipboard/attachment-789/photo.png",
      name: "photo.png",
      mimeType: "image/png",
    });
  });

  it("routes image files through persistBrowserFile", async () => {
    mockSaveClipboardImage.mockResolvedValue({
      path: "/tmp/posthog-code-clipboard/attachment-abc/img.png",
      name: "img.png",
      mimeType: "image/png",
    });

    const file = {
      name: "img.png",
      type: "image/png",
      arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
    } as unknown as File;

    const result = await persistBrowserFile(host, file);

    expect(result).toEqual({
      id: "/tmp/posthog-code-clipboard/attachment-abc/img.png",
      label: "img.png",
    });
  });

  it("persists arbitrary non-image files via saveClipboardFile", async () => {
    mockSaveClipboardFile.mockResolvedValue({
      path: "/tmp/posthog-code-clipboard/attachment-def/archive.zip",
      name: "archive.zip",
    });

    const file = {
      name: "archive.zip",
      type: "application/zip",
      arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
    } as unknown as File;

    await expect(persistBrowserFile(host, file)).resolves.toEqual({
      id: "/tmp/posthog-code-clipboard/attachment-def/archive.zip",
      label: "archive.zip",
    });

    expect(mockSaveClipboardFile).toHaveBeenCalledWith({
      base64Data: expect.any(String),
      originalName: "archive.zip",
    });
  });
});

describe("persistImageFilePath", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls downscaleImageFile and returns { id, label }", async () => {
    mockDownscaleImageFile.mockResolvedValue({
      path: "/tmp/posthog-code-clipboard/attachment-aaa/photo.jpg",
      name: "photo.jpg",
      mimeType: "image/jpeg",
    });

    const result = await persistImageFilePath(
      host,
      "/Users/me/Desktop/photo.png",
    );

    expect(mockDownscaleImageFile).toHaveBeenCalledWith({
      filePath: "/Users/me/Desktop/photo.png",
    });
    expect(result).toEqual({
      id: "/tmp/posthog-code-clipboard/attachment-aaa/photo.jpg",
      label: "photo.jpg",
    });
  });

  it("propagates errors from downscaleImageFile", async () => {
    mockDownscaleImageFile.mockRejectedValue(new Error("Image too large"));

    await expect(persistImageFilePath(host, "/big/image.png")).rejects.toThrow(
      "Image too large",
    );
  });
});

describe("resolveDroppedFile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns null when filePath is empty", async () => {
    const file = { name: "test.txt" } as File;
    expect(await resolveDroppedFile(host, file, "")).toBeNull();
  });

  it("returns file attachment directly for non-image files", async () => {
    const file = { name: "doc.pdf" } as File;
    const result = await resolveDroppedFile(host, file, "/Users/me/doc.pdf");

    expect(result).toEqual({ id: "/Users/me/doc.pdf", label: "doc.pdf" });
    expect(mockDownscaleImageFile).not.toHaveBeenCalled();
  });

  it("routes image files through downscaleImageFile", async () => {
    mockDownscaleImageFile.mockResolvedValue({
      path: "/tmp/posthog-code-clipboard/attachment-bbb/photo.jpg",
      name: "photo.jpg",
      mimeType: "image/jpeg",
    });

    const file = { name: "photo.png" } as File;
    const result = await resolveDroppedFile(host, file, "/Users/me/photo.png");

    expect(mockDownscaleImageFile).toHaveBeenCalledWith({
      filePath: "/Users/me/photo.png",
    });
    expect(result).toEqual({
      id: "/tmp/posthog-code-clipboard/attachment-bbb/photo.jpg",
      label: "photo.jpg",
    });
  });

  it("falls back to original path and invokes onDownscaleFailed when downscaling fails", async () => {
    mockDownscaleImageFile.mockRejectedValue(new Error("decode failed"));
    const onDownscaleFailed = vi.fn();

    const file = { name: "corrupt.png" } as File;
    expect(
      await resolveDroppedFile(host, file, "/Users/me/corrupt.png", {
        onDownscaleFailed,
      }),
    ).toEqual({
      id: "/Users/me/corrupt.png",
      label: "corrupt.png",
    });
    expect(onDownscaleFailed).toHaveBeenCalledOnce();
  });
});
