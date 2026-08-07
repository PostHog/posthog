import { z } from "zod";

export const runArtifactSchema = z.object({
  id: z.string().optional(),
  name: z.string().optional(),
  type: z.string().optional(),
  size: z.number().optional(),
  content_type: z.string().optional(),
  storage_path: z.string().optional(),
  uploaded_at: z.string().optional(),
  dismissed_at: z.string().nullish(),
});
export type RunArtifact = z.infer<typeof runArtifactSchema>;

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

/** Names a version by its position in a newest-first group. */
export function runArtifactVersionLabel(index: number, total: number): string {
  return index === 0 ? "Latest" : `Version ${total - index}`;
}

/**
 * A render key for one version of a file. Every identifying field goes in
 * because a manifest entry is only guaranteed to carry its name — two versions
 * collide only when they are indistinguishable, and then their order is moot.
 */
export function runArtifactVersionKey(artifact: {
  id?: string;
  storage_path?: string;
  uploaded_at?: string;
}): string {
  return [artifact.id, artifact.storage_path, artifact.uploaded_at].join(":");
}

interface VersionedArtifact {
  name?: string;
  uploaded_at?: string;
  dismissed_at?: string | null;
}

export interface RunArtifactVersions<T extends VersionedArtifact> {
  name: string;
  /** Newest upload first. Always holds at least one entry. */
  versions: T[];
  latest: T;
  /** Every version is dismissed, so the file as a whole is hidden. */
  dismissed: boolean;
}

/**
 * Group a run's artifacts into one entry per file name, newest upload first.
 *
 * Re-uploading a file is how an agent revises a deliverable, so the copies share
 * a name and only the newest is the current file. Earlier ones stay in the group
 * rather than being dropped, so a version the agent replaced is still reachable.
 */
export function groupRunArtifactVersions<T extends VersionedArtifact>(
  artifacts: T[],
): RunArtifactVersions<T>[] {
  const byName = new Map<string, T[]>();
  for (const artifact of artifacts) {
    if (!artifact.name) continue;
    const group = byName.get(artifact.name);
    if (group) group.push(artifact);
    else byName.set(artifact.name, [artifact]);
  }

  return [...byName].map(([name, group]) => {
    const versions = [...group].sort((a, b) =>
      (b.uploaded_at ?? "").localeCompare(a.uploaded_at ?? ""),
    );
    return {
      name,
      versions,
      latest: versions[0] as T,
      dismissed: versions.every((version) => Boolean(version.dismissed_at)),
    };
  });
}
