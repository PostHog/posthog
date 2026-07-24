import type {
  TaskRunArtifactMetadata,
  UploadableSkillSource,
} from "@posthog/shared";

export interface CloudArtifactUploadRequest {
  name: string;
  type: "user_attachment" | "skill_bundle";
  size: number;
  content_type?: string;
  source?: string;
  metadata?: TaskRunArtifactMetadata;
}

export interface CloudArtifactPresignedPost {
  url: string;
  fields: Record<string, string>;
}

export interface PreparedCloudArtifact extends CloudArtifactUploadRequest {
  id: string;
  presigned_post: CloudArtifactPresignedPost;
}

export interface FinalizedCloudArtifact {
  id: string;
}

export interface CloudArtifactClient {
  prepareTaskStagedArtifactUploads(
    taskId: string,
    artifacts: CloudArtifactUploadRequest[],
  ): Promise<PreparedCloudArtifact[]>;
  finalizeTaskStagedArtifactUploads(
    taskId: string,
    artifacts: PreparedCloudArtifact[],
  ): Promise<FinalizedCloudArtifact[]>;
  prepareTaskRunArtifactUploads(
    taskId: string,
    runId: string,
    artifacts: CloudArtifactUploadRequest[],
  ): Promise<PreparedCloudArtifact[]>;
  finalizeTaskRunArtifactUploads(
    taskId: string,
    runId: string,
    artifacts: PreparedCloudArtifact[],
  ): Promise<FinalizedCloudArtifact[]>;
}

export interface CloudSkillBundleRef {
  name: string;
  source: UploadableSkillSource;
  path: string;
}

export interface LocalSkillBundle {
  name: string;
  source: UploadableSkillSource;
  fileName: string;
  contentType: "application/zip";
  contentBase64: string;
  contentSha256: string;
  size: number;
}

export type BundleLocalSkill = (
  skillBundleRef: CloudSkillBundleRef,
) => Promise<LocalSkillBundle>;

/**
 * Expand tagged skill refs to include their transitively-declared dependency
 * skills so a cloud run gets every skill it needs, not just the tagged one.
 */
export type ResolveSkillBundleDependencies = (
  skillBundleRefs: CloudSkillBundleRef[],
) => Promise<CloudSkillBundleRef[]>;

export const CLOUD_ARTIFACT_SERVICE = Symbol.for(
  "posthog.core.sessions.cloudArtifactService",
);
export const CLOUD_ARTIFACT_READ_FILE_AS_BASE64 = Symbol.for(
  "posthog.core.sessions.cloudArtifactReadFileAsBase64",
);
export const CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL = Symbol.for(
  "posthog.core.sessions.cloudArtifactBundleLocalSkill",
);
export const CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES = Symbol.for(
  "posthog.core.sessions.cloudArtifactResolveSkillDependencies",
);
