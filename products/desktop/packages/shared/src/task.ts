export type {
  ArtifactType,
  Task,
  TaskRun,
  TaskRunArtifact,
  TaskRunArtifactMetadata,
  TaskRunEnvironment,
  TaskRunStatus,
} from "./domain-types";

export interface PostHogAPIConfig {
  apiUrl: string;
  publicApiUrl?: string;
  getApiKey: () => string | Promise<string>;
  refreshApiKey?: () => string | Promise<string>;
  projectId: number;
  userAgent?: string;
}
