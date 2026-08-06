import { z } from "zod";

export const runArtifactSchema = z.object({
  id: z.string().optional(),
  name: z.string().optional(),
  type: z.string().optional(),
  size: z.number().optional(),
  content_type: z.string().optional(),
  storage_path: z.string().optional(),
  uploaded_at: z.string().optional(),
  logical_artifact_id: z.string().optional(),
  artifact_version_id: z.string().optional(),
  artifact_version: z.number().int().positive().optional(),
});
export type RunArtifact = z.infer<typeof runArtifactSchema>;

const EDITABLE_TEXT_MAX_BYTES = 500_000;
const TEXT_EXTENSIONS = new Set([
  "c",
  "cc",
  "conf",
  "cpp",
  "css",
  "csv",
  "go",
  "h",
  "htm",
  "html",
  "ini",
  "java",
  "js",
  "json",
  "jsx",
  "log",
  "markdown",
  "md",
  "mdx",
  "py",
  "rb",
  "rs",
  "sh",
  "sql",
  "toml",
  "ts",
  "tsv",
  "tsx",
  "txt",
  "xml",
  "yaml",
  "yml",
]);
const TEXT_APPLICATION_TYPES = new Set([
  "application/javascript",
  "application/json",
  "application/sql",
  "application/toml",
  "application/xml",
  "application/x-yaml",
  "application/yaml",
]);

export function isEditableTextRunArtifact(artifact: RunArtifact): boolean {
  if (artifact.size === undefined || artifact.size > EDITABLE_TEXT_MAX_BYTES) {
    return false;
  }
  const contentType =
    (artifact.content_type ?? "").split(";", 1)[0]?.trim().toLowerCase() ?? "";
  const fileExtension = artifact.name?.split(".").at(-1)?.toLowerCase() ?? "";
  return (
    contentType.startsWith("text/") ||
    TEXT_APPLICATION_TYPES.has(contentType) ||
    TEXT_EXTENSIONS.has(fileExtension)
  );
}

/** Artifacts the agent hands back as deliverables, via the `upload_artifact` tool. */
export const OUTPUT_ARTIFACT_TYPES = ["output"] as const;

/**
 * The run's artifacts of the given types, in manifest order. A run's manifest
 * also carries plumbing the user never asked for — skill bundles, their own
 * attachments — so callers name the types they want.
 */
export function parseRunArtifacts(
  raw: unknown,
  types: readonly string[],
): RunArtifact[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    const parsed = runArtifactSchema.safeParse(entry);
    if (!parsed.success) return [];
    const { type } = parsed.data;
    return type && types.includes(type) ? [parsed.data] : [];
  });
}
