import { z } from "zod";

export const runArtifactSchema = z.object({
  id: z.string().optional(),
  name: z.string().optional(),
  type: z.string().optional(),
  size: z.number().optional(),
  content_type: z.string().optional(),
  storage_path: z.string().optional(),
  uploaded_at: z.string().optional(),
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
