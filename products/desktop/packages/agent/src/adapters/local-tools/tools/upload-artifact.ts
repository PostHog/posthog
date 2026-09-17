import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { createSandboxPosthogClient } from "../../../signed-commit-artefacts";
import type { TaskRunArtifact } from "../../../types";
import { defineLocalTool, type LocalToolResult } from "../registry";
import {
  type ArtifactUpload,
  MAX_ARTIFACT_UPLOAD_BYTES,
  uploadRunArtifact,
} from "./artifact-upload";

export const uploadArtifactTool = defineLocalTool({
  name: "upload_artifact",
  description:
    "Deliver a file you created to the user as a downloadable task artifact. " +
    "Call this for every non-code deliverable (reports, images, archives, data files, and similar output) " +
    "before your final response. The file must be inside the session workspace. Repository changes belong in git and should not be uploaded. " +
    "To revise a file you already delivered, read its current latest version first because the user may have edited it, " +
    "then upload your revision under the same name. The app shows the newest version and keeps the earlier ones available. " +
    "On success the result includes a download URL for the uploaded file, which you can reference in your final response.",
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

      const upload: ArtifactUpload = {
        name: args.name ?? path.basename(artifactPath),
        contentType: args.contentType ?? "application/octet-stream",
        content: await readFile(artifactPath),
        type: "output",
        source: "agent_output",
      };
      const entry = await uploadRunArtifact(
        client,
        ctx.taskId,
        ctx.taskRunId,
        upload,
      );

      const { name } = upload;
      const referenceUrl = getArtifactReferenceUrl(readDownloadUrl(entry));
      const linkText = referenceUrl
        ? ` Reference it as a markdown link: [${escapeMarkdownLinkLabel(name)}](<${referenceUrl}>)`
        : "";

      return {
        content: [
          {
            type: "text",
            text: `Uploaded ${name} as a downloadable task artifact.${linkText} Mention it in your final response.`,
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

// Read the download URL defensively: the field rides in on TaskRunArtifact once the
// api-client is regenerated against the updated OpenAPI spec, and older backends simply
// omit it.
function readDownloadUrl(artifact: TaskRunArtifact): string | undefined {
  return (artifact as { url?: string }).url;
}

function getArtifactReferenceUrl(
  downloadUrl: string | undefined,
): string | null {
  if (!downloadUrl) return null;

  try {
    const referenceUrl = new URL(downloadUrl);
    // Legacy backends return bearer credentials in the query string; stable API URLs do not.
    referenceUrl.search = "";
    referenceUrl.hash = "";
    referenceUrl.username = "";
    referenceUrl.password = "";
    return referenceUrl.toString();
  } catch {
    return null;
  }
}

function escapeMarkdownLinkLabel(label: string): string {
  return label.replace(/([\\[\]])/g, "\\$1");
}

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}
