import { beforeEach, describe, expect, it, vi } from "vitest";

const mockDownscaleImageFile = vi.hoisted(() => vi.fn());
const mockSaveClipboardImage = vi.hoisted(() => vi.fn());
const mockSaveClipboardFile = vi.hoisted(() => vi.fn());
const mockGetFilePath = vi.hoisted(() => vi.fn());
const mockToastWarning = vi.hoisted(() => vi.fn());

vi.mock("../hostApi", () => ({
  filePersistHost: {
    saveClipboardImage: mockSaveClipboardImage,
    saveClipboardText: vi.fn(),
    saveClipboardFile: mockSaveClipboardFile,
    downscaleImageFile: mockDownscaleImageFile,
  },
}));

vi.mock("@posthog/ui/utils/getFilePath", () => ({
  getFilePath: mockGetFilePath,
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { warning: mockToastWarning },
}));

import {
  resolveAndAttachDroppedFiles,
  resolveDroppedFile,
} from "./persistFile";

// A dropped File whose bytes can be read (browsers never expose an OS path).
function browserFile(name: string, type = ""): File {
  return {
    name,
    type,
    arrayBuffer: async () => new ArrayBuffer(0),
  } as unknown as File;
}

describe("resolveDroppedFile (UI glue)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns null when getFilePath returns empty string", async () => {
    mockGetFilePath.mockReturnValue("");

    const file = { name: "test.txt" } as File;
    expect(await resolveDroppedFile(file)).toBeNull();
  });

  it("returns file attachment directly for non-image files", async () => {
    mockGetFilePath.mockReturnValue("/Users/me/doc.pdf");

    const file = { name: "doc.pdf" } as File;
    const result = await resolveDroppedFile(file);

    expect(result).toEqual({ id: "/Users/me/doc.pdf", label: "doc.pdf" });
    expect(mockDownscaleImageFile).not.toHaveBeenCalled();
  });

  it("shows warning toast when image downscaling fails", async () => {
    mockGetFilePath.mockReturnValue("/Users/me/corrupt.png");
    mockDownscaleImageFile.mockRejectedValue(new Error("decode failed"));

    const file = { name: "corrupt.png" } as File;
    expect(await resolveDroppedFile(file)).toEqual({
      id: "/Users/me/corrupt.png",
      label: "corrupt.png",
    });
    expect(mockToastWarning).toHaveBeenCalledWith(
      "Image could not be downscaled",
      { description: "Attaching original file instead" },
    );
  });
});

describe("resolveAndAttachDroppedFiles", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("attaches path-resolved files directly", async () => {
    mockGetFilePath
      .mockReturnValueOnce("/Users/me/a.txt")
      .mockReturnValueOnce("/Users/me/b.txt");

    const files = [
      browserFile("a.txt"),
      browserFile("b.txt"),
    ] as unknown as FileList;
    Object.defineProperty(files, "length", { value: 2 });

    const addAttachment = vi.fn();
    await resolveAndAttachDroppedFiles(files, addAttachment);

    expect(addAttachment).toHaveBeenCalledTimes(2);
    expect(addAttachment).toHaveBeenCalledWith({
      id: "/Users/me/a.txt",
      label: "a.txt",
    });
    expect(addAttachment).toHaveBeenCalledWith({
      id: "/Users/me/b.txt",
      label: "b.txt",
    });
    expect(mockSaveClipboardFile).not.toHaveBeenCalled();
  });

  it("falls back to reading bytes when the file has no path (browser drop)", async () => {
    // Browsers never expose an OS path, so getFilePath returns "" for every
    // dropped file; the helper must persist the bytes instead of skipping.
    mockGetFilePath.mockReturnValue("");
    mockSaveClipboardFile.mockResolvedValue({
      path: "/web-attachment/generated-id",
      name: "notes.txt",
    });

    const files = [browserFile("notes.txt")] as unknown as FileList;
    Object.defineProperty(files, "length", { value: 1 });

    const addAttachment = vi.fn();
    await resolveAndAttachDroppedFiles(files, addAttachment);

    expect(mockSaveClipboardFile).toHaveBeenCalledTimes(1);
    expect(addAttachment).toHaveBeenCalledWith({
      id: "/web-attachment/generated-id",
      label: "notes.txt",
    });
  });

  it("persists dropped images through saveClipboardImage when there is no path", async () => {
    mockGetFilePath.mockReturnValue("");
    mockSaveClipboardImage.mockResolvedValue({
      path: "/web-attachment/image-id",
      name: "shot.png",
      mimeType: "image/png",
    });

    const files = [browserFile("shot.png", "image/png")] as unknown as FileList;
    Object.defineProperty(files, "length", { value: 1 });

    const addAttachment = vi.fn();
    await resolveAndAttachDroppedFiles(files, addAttachment);

    expect(mockSaveClipboardImage).toHaveBeenCalledTimes(1);
    expect(addAttachment).toHaveBeenCalledWith({
      id: "/web-attachment/image-id",
      label: "shot.png",
    });
  });
});
