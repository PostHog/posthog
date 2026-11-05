import { basename, join } from "node:path";

/** A file name safe to write under the repository, or `attachment` when nothing usable is left. */
export function safeArtifactFileName(name: string): string {
  const normalizedName = basename(name)
    .trim()
    .replace(/[^\w.-]/g, "_");
  if (normalizedName.length === 0 || /^\.+$/.test(normalizedName)) {
    return "attachment";
  }
  return normalizedName;
}

/**
 * Where a run's attachment lives on disk: `.posthog/attachments/<runId>/<artifactId>/<name>`.
 * Every harness writes this layout, and the clients read the run and artifact ids back out of it.
 */
export function attachmentFilePath(
  repositoryPath: string | undefined,
  runId: string,
  artifact: { id?: string; name: string },
): string {
  const safeName = safeArtifactFileName(artifact.name);
  return join(
    repositoryPath ?? "/tmp/workspace",
    ".posthog",
    "attachments",
    runId,
    artifact.id ?? safeName,
    safeName,
  );
}
