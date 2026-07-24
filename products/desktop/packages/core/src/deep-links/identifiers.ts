import type { GithubRef } from "@posthog/shared";
import type {
  ANALYTICS_EVENTS,
  DeepLinkIssueFailedProperties,
  DeepLinkIssueProperties,
  DeepLinkNewTaskProperties,
  DeepLinkPlanProperties,
} from "@posthog/shared/analytics-events";

export const NEW_TASK_LINK_RESOLVER = Symbol.for(
  "posthog.core.newTaskLinkResolver",
);

export const GITHUB_ISSUE_CLIENT = Symbol.for("posthog.core.githubIssueClient");

export interface GitHubIssueClient {
  getGithubIssue(
    owner: string,
    repo: string,
    issueNumber: number,
  ): Promise<GithubRef | null>;
}

export interface TaskInputNavigation {
  initialPrompt?: string;
  initialCloudRepository?: string;
  initialModel?: string;
  initialMode?: string;
}

export type NewTaskLinkAnalytics =
  | {
      event: typeof ANALYTICS_EVENTS.DEEP_LINK_NEW_TASK;
      properties: DeepLinkNewTaskProperties;
    }
  | {
      event: typeof ANALYTICS_EVENTS.DEEP_LINK_PLAN;
      properties: DeepLinkPlanProperties;
    }
  | {
      event: typeof ANALYTICS_EVENTS.DEEP_LINK_ISSUE;
      properties: DeepLinkIssueProperties;
    }
  | {
      event: typeof ANALYTICS_EVENTS.DEEP_LINK_ISSUE_FAILED;
      properties: DeepLinkIssueFailedProperties;
    };

export type NewTaskLinkResolution =
  | {
      kind: "navigate";
      navigation: TaskInputNavigation;
      analytics: NewTaskLinkAnalytics;
    }
  | {
      kind: "not_found";
      title: string;
      description: string;
      analytics: NewTaskLinkAnalytics;
    }
  | {
      kind: "fetch_failed";
      title: string;
      description: string;
      analytics: NewTaskLinkAnalytics;
    };
