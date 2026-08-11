import type { ArtifactType, TaskRunArtifact } from "@posthog/shared";

/**
 * Artifact types the task detail "Files" section surfaces: everything the agent
 * produced as a deliverable. `skill_bundle` is a machine payload the sandbox
 * consumes, and `user_attachment` is the user's own upload which already shows
 * in the conversation — neither belongs in the deliverables list.
 */
export const DELIVERABLE_ARTIFACT_TYPES = [
  "plan",
  "context",
  "reference",
  "output",
  "artifact",
] as const satisfies readonly ArtifactType[];

export type DeliverableArtifactType =
  (typeof DELIVERABLE_ARTIFACT_TYPES)[number];

const DELIVERABLE_LABELS: Record<DeliverableArtifactType, string> = {
  plan: "Plan",
  context: "Context",
  reference: "Reference",
  output: "Output",
  artifact: "Artifact",
};

function isDeliverableType(
  type: string | undefined,
): type is DeliverableArtifactType {
  return type !== undefined && type in DELIVERABLE_LABELS;
}

export function isDeliverableArtifact(
  artifact: Pick<TaskRunArtifact, "type">,
): boolean {
  return isDeliverableType(artifact.type);
}

/** Short badge label, or `null` for a type that has no place in the list. */
export function artifactTypeLabel(type: string | undefined): string | null {
  return isDeliverableType(type) ? DELIVERABLE_LABELS[type] : null;
}

/**
 * Groups the manifest by type so same-kind files sit together, in the order
 * `DELIVERABLE_ARTIFACT_TYPES` declares (plan first, generated output last).
 * Stable within a group, so the server's ordering survives.
 */
export function groupArtifactsByType<T extends Pick<TaskRunArtifact, "type">>(
  artifacts: readonly T[],
): T[] {
  return DELIVERABLE_ARTIFACT_TYPES.flatMap((type) =>
    artifacts.filter((artifact) => artifact.type === type),
  );
}

/** The list the "Files" section renders: deliverables only, grouped by type. */
export function selectDeliverableArtifacts<
  T extends Pick<TaskRunArtifact, "type">,
>(artifacts: readonly T[]): T[] {
  return groupArtifactsByType(artifacts.filter(isDeliverableArtifact));
}
