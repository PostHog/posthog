import type { AcpMessage } from "@posthog/shared";
import {
  createCompletedToolCallTracker,
  useCompletedToolCalls,
} from "./completedToolCalls";

const UPLOAD_ARTIFACT_TOOL = "upload_artifact";

export function createArtifactUploadTracker() {
  return createCompletedToolCallTracker(UPLOAD_ARTIFACT_TOOL);
}

export function countCompletedArtifactUploads(events: AcpMessage[]): number {
  return createArtifactUploadTracker().update(events);
}

export function useCompletedArtifactUploads(events: AcpMessage[]): number {
  return useCompletedToolCalls(events, UPLOAD_ARTIFACT_TOOL);
}
