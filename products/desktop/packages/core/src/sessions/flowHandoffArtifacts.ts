import type { TaskRunArtifact } from "@posthog/shared";
import {
  groupRunArtifactVersions,
  OUTPUT_ARTIFACT_TYPES,
  parseRunArtifacts,
} from "../canvas/runArtifactSchemas";

/**
 * The artifact id for one version of a flow handoff, or null when that version
 * is not stored yet. Flow versions count from 1 and the manifest groups
 * newest first, so version N is the Nth entry from the end.
 */
function handoffVersions(runArtifacts: unknown, name: string) {
  return (
    groupRunArtifactVersions(
      parseRunArtifacts(runArtifacts, OUTPUT_ARTIFACT_TYPES),
    ).find((group) => group.name === name)?.versions ?? []
  );
}

export function findHandoffArtifactId(
  runArtifacts: unknown,
  name: string,
  version: number,
): string | null {
  const versions = handoffVersions(runArtifacts, name);
  if (version < 1 || versions.length < version) {
    return null;
  }
  return versions[versions.length - version]?.id ?? null;
}

/** The last stored version of the document, whatever its number. */
export function newestHandoffArtifactId(
  runArtifacts: unknown,
  name: string,
): string | null {
  return handoffVersions(runArtifacts, name)[0]?.id ?? null;
}

/** The run artifact operations a handoff needs. The session service has them. */
export interface FlowHandoffArtifactStore {
  ensureTaskRunId(taskId: string): Promise<string>;
  getCloudRunArtifacts(
    taskId: string,
    runId: string,
  ): Promise<TaskRunArtifact[]>;
  uploadCloudRunArtifactVersion(
    taskId: string,
    runId: string,
    name: string,
    content: string,
    contentType?: string,
  ): Promise<string>;
}

export interface FlowHandoffDocument {
  taskId: string;
  name: string;
  version: number;
  markdown: string;
}

/**
 * The stored copy of one handoff version, uploaded if it is not there yet.
 * Reading the manifest first keeps a reopened task from adding a duplicate
 * version, and returns the id of the version the card names rather than
 * whatever an upload answers with.
 */
export async function ensureFlowHandoffArtifact(
  store: FlowHandoffArtifactStore,
  document: FlowHandoffDocument,
): Promise<{ runId: string; artifactId: string }> {
  const { taskId, name, version, markdown } = document;
  const runId = await store.ensureTaskRunId(taskId);

  const stored = await store.getCloudRunArtifacts(taskId, runId);
  const existingId = findHandoffArtifactId(stored, name, version);
  if (existingId) {
    return { runId, artifactId: existingId };
  }

  await store.uploadCloudRunArtifactVersion(
    taskId,
    runId,
    name,
    markdown,
    "text/markdown",
  );
  const uploaded = await store.getCloudRunArtifacts(taskId, runId);
  const artifactId =
    findHandoffArtifactId(uploaded, name, version) ??
    newestHandoffArtifactId(uploaded, name);
  if (!artifactId) {
    throw new Error("The handoff document was not stored");
  }
  return { runId, artifactId };
}
