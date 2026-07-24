import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { createSandboxPosthogClient } from "../../../signed-commit-artefacts";
import { defineLocalTool, type LocalToolResult } from "../registry";

const MAX_ARTIFACT_UPLOAD_BYTES = 30 * 1024 * 1024;

export const uploadArtifactTool = defineLocalTool({
  name: "upload_artifact",
  description:
    "Deliver a file you created to the user as a downloadable task artifact. " +
    "Call this for every non-code deliverable (reports, images, archives, data files, and similar output) " +
    "before your final response. The file must be inside the session workspace. Repository changes belong in git and should not be uploaded.",
  schema: {
    path: z
      .string()
      .min(1)
      .describe(
        "Absolute path, or a path relative to the session working directory.",
      ),
    name: z
      .string()
      .min(1)
      .optional()
      .describe("Download filename. Defaults to the source filename."),
    contentType: z
      .string()
      .min(1)
      .optional()
      .describe("MIME type. Defaults to application/octet-stream."),
  },
  alwaysLoad: true,
  isEnabled: (ctx, meta) =>
    meta?.environment === "cloud" && !!ctx.taskId && !!ctx.taskRunId,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    if (!ctx.taskId || !ctx.taskRunId) {
      return errorResult("Artifact upload is not available in this session.");
    }

    try {
      const workspace = await realpath(ctx.cwd);
      const requestedPath = path.resolve(ctx.cwd, args.path);
      const artifactPath = await realpath(requestedPath);
      if (
        artifactPath !== workspace &&
        !artifactPath.startsWith(`${workspace}${path.sep}`)
      ) {
        return errorResult("Artifact must be inside the session workspace.");
      }

      const fileStat = await stat(artifactPath);
      if (!fileStat.isFile()) {
        return errorResult("Artifact path must point to a file.");
      }
      if (fileStat.size > MAX_ARTIFACT_UPLOAD_BYTES) {
        return errorResult("Artifact exceeds the 30 MB upload limit.");
      }

      const client = createSandboxPosthogClient();
      if (!client) {
        return errorResult(
          "PostHog artifact storage is not configured in this sandbox.",
        );
      }

      const name = args.name ?? path.basename(artifactPath);
      const contentType = args.contentType ?? "application/octet-stream";
      const prepared = await client.prepareTaskArtifactUploads(
        ctx.taskId,
        ctx.taskRunId,
        [
          {
            name,
            type: "output",
            size: fileStat.size,
            content_type: contentType,
          },
        ],
      );
      const upload = prepared[0];
      if (!upload) {
        return errorResult("PostHog did not prepare the artifact upload.");
      }

      const form = new FormData();
      for (const [key, value] of Object.entries(upload.presigned_post.fields)) {
        form.append(key, value);
      }
      form.append(
        "file",
        new Blob([await readFile(artifactPath)], { type: contentType }),
        name,
      );
      const response = await fetch(upload.presigned_post.url, {
        method: "POST",
        body: form,
      });
      if (!response.ok) {
        return errorResult(
          `Artifact storage upload failed (${response.status}).`,
        );
      }

      const finalized = await client.finalizeTaskArtifactUploads(
        ctx.taskId,
        ctx.taskRunId,
        [
          {
            id: upload.id,
            name,
            type: "output",
            storage_path: upload.storage_path,
            content_type: contentType,
          },
        ],
      );
      if (
        !finalized.some(
          (artifact) => artifact.storage_path === upload.storage_path,
        )
      ) {
        return errorResult("PostHog did not confirm the artifact upload.");
      }

      return {
        content: [
          {
            type: "text",
            text: `Uploaded ${name} as a downloadable task artifact. Mention it in your final response.`,
          },
        ],
      };
    } catch (error) {
      return errorResult(
        `Artifact upload failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  },
});

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}
