import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const photoBytes = new Uint8Array([137, 80, 78, 71]);
  class MockFile extends Blob {
    constructor(_uri: string) {
      super([photoBytes], { type: "image/png" });
    }
  }

  return {
    client: {
      finalizeTaskStagedArtifactUploads: vi.fn(),
      prepareTaskStagedArtifactUploads: vi.fn(),
    },
    expoFetch: vi.fn(),
    MockFile,
    photoBytes,
  };
});

vi.mock("expo/fetch", () => ({ fetch: mocks.expoFetch }));
vi.mock("expo-file-system", () => ({ File: mocks.MockFile }));
vi.mock("expo-image-picker", () => ({
  UIImagePickerPreferredAssetRepresentationMode: { Compatible: "compatible" },
  launchImageLibraryAsync: vi.fn(),
}));
vi.mock("@/lib/client", () => ({ getClient: () => mocks.client }));

import {
  resetSentPhotos,
  sentPhotoUri,
  uploadStagedPhotos,
} from "./attachments";

const photo = {
  id: "photo-id",
  uri: "file:///photo.png",
  name: "photo.png",
  mimeType: "image/png",
  size: mocks.photoBytes.byteLength,
};

beforeEach(() => {
  vi.clearAllMocks();
  resetSentPhotos();
  mocks.client.prepareTaskStagedArtifactUploads.mockResolvedValue([
    {
      id: "prepared-id",
      presigned_post: {
        fields: { key: "artifact-key" },
        url: "https://uploads.example.com",
      },
    },
  ]);
  mocks.client.finalizeTaskStagedArtifactUploads.mockResolvedValue([
    { id: "artifact-id" },
  ]);
});

describe("uploadStagedPhotos", () => {
  it("sends the selected photo bytes through Expo fetch", async () => {
    let uploadedBytes: Uint8Array | undefined;
    mocks.expoFetch.mockImplementation(async (_url, init) => {
      const file = (init?.body as FormData).get("file") as Blob;
      uploadedBytes = new Uint8Array(await file.arrayBuffer());
      return { ok: true };
    });

    const result = await uploadStagedPhotos("task-id", [photo]);

    expect(uploadedBytes).toEqual(mocks.photoBytes);
    expect(mocks.expoFetch).toHaveBeenCalledWith(
      "https://uploads.example.com",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result).toEqual(["artifact-id"]);
    expect(sentPhotoUri("task-id", "artifact-id")).toBe("file:///photo.png");
  });
});

describe("sentPhotoUri", () => {
  beforeEach(() => {
    mocks.expoFetch.mockResolvedValue({ ok: true });
  });

  it("shows a sent photo only in the task it was sent to", async () => {
    await uploadStagedPhotos("task-id", [photo]);

    expect(sentPhotoUri("other-task-id", "artifact-id")).toBeNull();
  });

  it("forgets sent photos when the account changes", async () => {
    await uploadStagedPhotos("task-id", [photo]);
    resetSentPhotos();

    expect(sentPhotoUri("task-id", "artifact-id")).toBeNull();
  });
});
