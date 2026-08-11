import { describe, expect, it } from "vitest";
import {
  buildArtifactUploadRequest,
  deriveUploadContentType,
  MAX_PDF_UPLOAD_BYTES,
  MAX_UPLOAD_BYTES,
  maxUploadBytes,
  uploadSizeError,
} from "./artifactUpload";

describe("deriveUploadContentType", () => {
  it.each<[string, string | null | undefined, string]>([
    ["shot.png", "image/png", "image/png"],
    ["shot.png", "image/png; charset=binary", "image/png"],
    ["notes.md", undefined, "text/markdown"],
    ["notes.md", null, "text/markdown"],
    ["notes.md", "", "text/markdown"],
    ["data.csv", "application/octet-stream", "text/csv"],
    ["report.PDF", "application/octet-stream", "application/pdf"],
    ["mystery.bin", "application/octet-stream", "application/octet-stream"],
    ["noextension", undefined, "application/octet-stream"],
  ])("derives %s (%s) as %s", (fileName, pickerMime, expected) => {
    expect(deriveUploadContentType(fileName, pickerMime)).toBe(expected);
  });
});

describe("maxUploadBytes", () => {
  it.each<[string, string, number]>([
    ["notes.md", "text/markdown", MAX_UPLOAD_BYTES],
    ["report.pdf", "application/octet-stream", MAX_PDF_UPLOAD_BYTES],
    ["report", "application/pdf", MAX_PDF_UPLOAD_BYTES],
  ])("limits %s (%s) to %s bytes", (fileName, contentType, expected) => {
    expect(maxUploadBytes(fileName, contentType)).toBe(expected);
  });
});

describe("uploadSizeError", () => {
  it("accepts a file inside the limit", () => {
    expect(uploadSizeError("notes.md", "text/markdown", 1_024)).toBeNull();
  });

  it("rejects an empty file", () => {
    expect(uploadSizeError("notes.md", "text/markdown", 0)).toBe(
      "notes.md is empty.",
    );
  });

  it("rejects an oversized file with the general limit", () => {
    expect(
      uploadSizeError("big.zip", "application/zip", MAX_UPLOAD_BYTES + 1),
    ).toBe("big.zip exceeds the 30MB upload limit.");
  });

  it("rejects an oversized PDF with the tighter PDF limit", () => {
    expect(
      uploadSizeError("doc.pdf", "application/pdf", MAX_PDF_UPLOAD_BYTES + 1),
    ).toBe("doc.pdf exceeds the 10MB upload limit.");
  });
});

describe("buildArtifactUploadRequest", () => {
  it("marks the upload as a user attachment from mobile", () => {
    expect(
      buildArtifactUploadRequest(
        { fileName: "data.csv", mimeType: "application/octet-stream" },
        2_048,
      ),
    ).toEqual({
      name: "data.csv",
      type: "user_attachment",
      source: "posthog_mobile",
      size: 2_048,
      content_type: "text/csv",
    });
  });
});
