import { describe, expect, it, vi } from "vitest";
import type {
  BundleLocalSkill,
  CloudArtifactClient,
  ResolveSkillBundleDependencies,
} from "./cloudArtifactIdentifiers";
import {
  CLOUD_ATTACHMENT_MAX_SIZE_BYTES,
  CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES,
  CloudArtifactService,
} from "./cloudArtifactService";

function makeClient(): CloudArtifactClient {
  return {
    prepareTaskStagedArtifactUploads: vi.fn(),
    finalizeTaskStagedArtifactUploads: vi.fn(),
    prepareTaskRunArtifactUploads: vi.fn(),
    finalizeTaskRunArtifactUploads: vi.fn(),
  };
}

const passthroughDeps: ResolveSkillBundleDependencies = async (refs) => refs;

const bundleLocalSkill: BundleLocalSkill = vi.fn(async (skillBundleRef) => {
  const contentBase64 = btoa("skill-bundle");
  return {
    name: skillBundleRef.name,
    source: skillBundleRef.source,
    fileName: `${skillBundleRef.name}.zip`,
    contentType: "application/zip" as const,
    contentBase64,
    contentSha256:
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    size: 12,
  };
});

describe("CloudArtifactService", () => {
  it("returns empty ids when no file paths are provided", async () => {
    const service = new CloudArtifactService(
      vi.fn(),
      bundleLocalSkill,
      passthroughDeps,
    );
    expect(
      await service.uploadRunAttachments(makeClient(), "t", "r", []),
    ).toEqual([]);
  });

  it("rejects attachments that exceed the max size", async () => {
    const oversized = CLOUD_ATTACHMENT_MAX_SIZE_BYTES + 1;
    const base64 = btoa("a".repeat(oversized));
    const service = new CloudArtifactService(
      vi.fn().mockResolvedValue(base64),
      bundleLocalSkill,
      passthroughDeps,
    );

    await expect(
      service.uploadRunAttachments(makeClient(), "task-1", "run-1", [
        "/tmp/huge.bin",
      ]),
    ).rejects.toThrow(/exceeds the 30MB attachment limit/);
  });

  it("rejects PDFs that exceed the stricter cloud limit", async () => {
    const oversized = CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES + 1;
    const base64 = btoa("a".repeat(oversized));
    const service = new CloudArtifactService(
      vi.fn().mockResolvedValue(base64),
      bundleLocalSkill,
      passthroughDeps,
    );

    await expect(
      service.uploadRunAttachments(makeClient(), "task-1", "run-1", [
        "/tmp/large.pdf",
      ]),
    ).rejects.toThrow(
      /exceeds the 10MB attachment limit for PDFs in cloud runs/,
    );
  });

  it("throws when a file cannot be read", async () => {
    const service = new CloudArtifactService(
      vi.fn().mockResolvedValue(null),
      bundleLocalSkill,
      passthroughDeps,
    );

    await expect(
      service.uploadRunAttachments(makeClient(), "task-1", "run-1", [
        "/tmp/missing.txt",
      ]),
    ).rejects.toThrow(/Unable to read attached file missing\.txt/);
  });

  it("runs prepare, POST, finalize and tallies the artifact ids", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({ ok: true } as Response);
    const base64 = btoa("hello");
    const service = new CloudArtifactService(
      vi.fn().mockResolvedValue(base64),
      bundleLocalSkill,
      passthroughDeps,
    );

    const client = makeClient();
    (
      client.prepareTaskRunArtifactUploads as ReturnType<typeof vi.fn>
    ).mockResolvedValue([
      {
        id: "prep-1",
        name: "a.txt",
        type: "user_attachment",
        size: 5,
        presigned_post: { url: "https://s3/upload", fields: { key: "k" } },
      },
    ]);
    (
      client.finalizeTaskRunArtifactUploads as ReturnType<typeof vi.fn>
    ).mockResolvedValue([{ id: "artifact-1" }]);

    const ids = await service.uploadRunAttachments(client, "task-1", "run-1", [
      "/tmp/a.txt",
    ]);

    expect(ids).toEqual(["artifact-1"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "https://s3/upload",
      expect.objectContaining({ method: "POST" }),
    );
    fetchMock.mockRestore();
  });

  it("uploads local skill bundles as skill bundle artifacts", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({ ok: true } as Response);
    const service = new CloudArtifactService(
      vi.fn(),
      bundleLocalSkill,
      passthroughDeps,
    );
    const client = makeClient();

    (
      client.prepareTaskRunArtifactUploads as ReturnType<typeof vi.fn>
    ).mockResolvedValue([
      {
        id: "prep-1",
        name: "local-skill.zip",
        type: "skill_bundle",
        size: 12,
        presigned_post: { url: "https://s3/upload", fields: { key: "k" } },
      },
    ]);
    (
      client.finalizeTaskRunArtifactUploads as ReturnType<typeof vi.fn>
    ).mockResolvedValue([{ id: "skill-artifact-1" }]);

    const ids = await service.uploadRunAttachments(
      client,
      "task-1",
      "run-1",
      [],
      [{ name: "local-skill", source: "user", path: "/tmp/local-skill" }],
    );

    expect(ids).toEqual(["skill-artifact-1"]);
    expect(client.prepareTaskRunArtifactUploads).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      [
        expect.objectContaining({
          name: "local-skill.zip",
          type: "skill_bundle",
          content_type: "application/zip",
          metadata: expect.objectContaining({
            skill_name: "local-skill",
            skill_source: "user",
            bundle_format: "zip",
            schema_version: 1,
          }),
        }),
      ],
    );
    fetchMock.mockRestore();
  });

  it("uploads dependency skills the resolver adds to a tagged skill", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({ ok: true } as Response);
    const resolveDeps: ResolveSkillBundleDependencies = vi.fn(async (refs) => [
      ...refs,
      { name: "dep-skill", source: "user", path: "/tmp/dep-skill" },
    ]);
    const service = new CloudArtifactService(
      vi.fn(),
      bundleLocalSkill,
      resolveDeps,
    );
    const client = makeClient();

    (
      client.prepareTaskRunArtifactUploads as ReturnType<typeof vi.fn>
    ).mockImplementation((_taskId, _runId, uploads: unknown[]) =>
      uploads.map((_upload, index) => ({
        id: `prep-${index}`,
        name: `skill-${index}.zip`,
        type: "skill_bundle",
        size: 12,
        presigned_post: { url: "https://s3/upload", fields: { key: "k" } },
      })),
    );
    (
      client.finalizeTaskRunArtifactUploads as ReturnType<typeof vi.fn>
    ).mockResolvedValue([{ id: "primary-1" }, { id: "dep-1" }]);

    const ids = await service.uploadRunAttachments(
      client,
      "task-1",
      "run-1",
      [],
      [{ name: "primary-skill", source: "user", path: "/tmp/primary-skill" }],
    );

    expect(resolveDeps).toHaveBeenCalledWith([
      { name: "primary-skill", source: "user", path: "/tmp/primary-skill" },
    ]);
    expect(bundleLocalSkill).toHaveBeenCalledWith(
      expect.objectContaining({ name: "dep-skill" }),
    );
    expect(ids).toEqual(["primary-1", "dep-1"]);
    fetchMock.mockRestore();
  });
});
