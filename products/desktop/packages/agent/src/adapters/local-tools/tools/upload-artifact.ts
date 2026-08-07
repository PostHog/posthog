import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { PostHogAPIClient } from "../../../posthog-api";
import { createSandboxPosthogClient } from "../../../signed-commit-artefacts";
import type { TaskRunArtifact } from "../../../types";
import { defineLocalTool, type LocalToolResult } from "../registry";

const MAX_ARTIFACT_UPLOAD_BYTES = 30 * 1024 * 1024;
// The inline fallback base64-encodes the file into a JSON body, so it is held to a lower
// ceiling than a direct-to-storage POST to stay under the API's request size limit.
const MAX_INLINE_UPLOAD_BYTES = 10 * 1024 * 1024;

export const uploadArtifactTool = defineLocalTool({
  name: "upload_artifact",
  description:
    "Deliver a file you created to the user as a downloadable task artifact. " +
    "Call this for every non-code deliverable (reports, images, archives, data files, and similar output) " +
    "before your final response. The file must be inside the session workspace. Repository changes belong in git and should not be uploaded. " +
    "To revise a file you already delivered, upload it again under the same name: the app shows the newest version " +
    "and keeps the earlier ones available. " +
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

      const upload = {
        name: args.name ?? path.basename(artifactPath),
        contentType: args.contentType ?? "application/octet-stream",
        content: await readFile(artifactPath),
      };

      let downloadUrl: string | undefined;
      try {
        downloadUrl = await uploadDirect(
          client,
          ctx.taskId,
          ctx.taskRunId,
          upload,
        );
      } catch (error) {
        // A direct upload needs the agent to reach object storage itself, which fails in
        // any environment where the sandbox can reach the PostHog API but not the storage
        // host (a split network, or an egress allowlist that omits the bucket). The inline
        // upload goes through the API instead, so retry there before surfacing a failure.
        if (upload.content.byteLength > MAX_INLINE_UPLOAD_BYTES) {
          throw error;
        }
        downloadUrl = await uploadInline(
          client,
          ctx.taskId,
          ctx.taskRunId,
          upload,
        );
      }

      const { name } = upload;
      const referenceUrl = getArtifactReferenceUrl(downloadUrl);
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

interface ArtifactUpload {
  name: string;
  contentType: string;
  content: Buffer;
}

/** Reserve a storage key, POST the bytes straight to object storage, then attach them. */
async function uploadDirect(
  client: PostHogAPIClient,
  taskId: string,
  taskRunId: string,
  { name, contentType, content }: ArtifactUpload,
): Promise<string | undefined> {
  const [prepared] = await client.prepareTaskArtifactUploads(
    taskId,
    taskRunId,
    [
      {
        name,
        type: "output",
        source: "agent_output",
        size: content.byteLength,
        content_type: contentType,
      },
    ],
  );
  if (!prepared) {
    throw new Error("PostHog did not prepare the artifact upload.");
  }

  const form = new FormData();
  for (const [key, value] of Object.entries(prepared.presigned_post.fields)) {
    form.append(key, value);
  }
  form.append(
    "file",
    new Blob([new Uint8Array(content)], { type: contentType }),
    name,
  );
  const response = await fetch(prepared.presigned_post.url, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new Error(`Artifact storage upload failed (${response.status}).`);
  }

  const finalized = await client.finalizeTaskArtifactUploads(
    taskId,
    taskRunId,
    [
      {
        id: prepared.id,
        name,
        type: "output",
        source: "agent_output",
        storage_path: prepared.storage_path,
        content_type: contentType,
      },
    ],
  );
  const entry = finalized.find(
    (artifact) => artifact.storage_path === prepared.storage_path,
  );
  if (!entry) {
    throw new Error("PostHog did not confirm the artifact upload.");
  }
  return readDownloadUrl(entry);
}

/** Send the bytes through the PostHog API and let the backend write them to storage. */
async function uploadInline(
  client: PostHogAPIClient,
  taskId: string,
  taskRunId: string,
  { name, contentType, content }: ArtifactUpload,
): Promise<string | undefined> {
  const manifest = await client.uploadTaskArtifacts(taskId, taskRunId, [
    {
      name,
      type: "output",
      source: "agent_output",
      content: content.toString("base64"),
      content_encoding: "base64",
      content_type: contentType,
    },
  ]);
  // The endpoint returns the run's whole manifest with the new entry appended last.
  const entry = manifest.at(-1);
  if (!entry) {
    throw new Error("PostHog did not confirm the artifact upload.");
  }
  return readDownloadUrl(entry);
}

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
