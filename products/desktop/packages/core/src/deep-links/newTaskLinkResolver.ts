import type { NewTaskLinkPayload } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { inject, injectable } from "inversify";
import {
  GITHUB_ISSUE_CLIENT,
  type GitHubIssueClient,
  NEW_TASK_LINK_RESOLVER,
  type NewTaskLinkResolution,
} from "./identifiers";

export { NEW_TASK_LINK_RESOLVER };

const GITHUB_PR_TAG_REGEX = /<github_pr\b[^>]*\burl="([^"]+)"[^>]*\/>/g;

function inferRepositoryFromPullRequests(
  prompt: string | undefined,
): string | undefined {
  if (!prompt) return undefined;

  const repositories = new Set<string>();
  for (const match of prompt.matchAll(GITHUB_PR_TAG_REGEX)) {
    try {
      const url = new URL(match[1]);
      const pathParts = url.pathname.split("/").filter(Boolean);
      if (
        url.hostname !== "github.com" ||
        pathParts.length !== 4 ||
        pathParts[2] !== "pull"
      ) {
        continue;
      }
      repositories.add(`${pathParts[0]}/${pathParts[1]}`);
    } catch {}
  }

  return repositories.size === 1
    ? repositories.values().next().value
    : undefined;
}

@injectable()
export class NewTaskLinkResolver {
  constructor(
    @inject(GITHUB_ISSUE_CLIENT)
    private readonly github: GitHubIssueClient,
  ) {}

  async resolve(payload: NewTaskLinkPayload): Promise<NewTaskLinkResolution> {
    switch (payload.action) {
      case "new":
        return this.resolveNew(payload);
      case "plan":
        return this.resolvePlan(payload);
      case "issue":
        return this.resolveIssue(payload);
    }
  }

  private resolveNew(
    payload: Extract<NewTaskLinkPayload, { action: "new" }>,
  ): NewTaskLinkResolution {
    return {
      kind: "navigate",
      navigation: {
        initialPrompt: payload.prompt,
        initialCloudRepository:
          payload.repo ?? inferRepositoryFromPullRequests(payload.prompt),
        initialModel: payload.model,
        initialMode: payload.mode,
      },
      analytics: {
        event: ANALYTICS_EVENTS.DEEP_LINK_NEW_TASK,
        properties: {
          has_prompt: !!payload.prompt,
          has_repo: !!payload.repo,
          mode: payload.mode,
          model: payload.model,
        },
      },
    };
  }

  private resolvePlan(
    payload: Extract<NewTaskLinkPayload, { action: "plan" }>,
  ): NewTaskLinkResolution {
    return {
      kind: "navigate",
      navigation: {
        initialPrompt: payload.plan,
        initialCloudRepository: payload.repo,
        initialModel: payload.model,
        initialMode: payload.mode,
      },
      analytics: {
        event: ANALYTICS_EVENTS.DEEP_LINK_PLAN,
        properties: {
          has_repo: !!payload.repo,
          mode: payload.mode,
          model: payload.model,
          plan_length_chars: payload.plan.length,
        },
      },
    };
  }

  private async resolveIssue(
    payload: Extract<NewTaskLinkPayload, { action: "issue" }>,
  ): Promise<NewTaskLinkResolution> {
    let issue: Awaited<ReturnType<GitHubIssueClient["getGithubIssue"]>>;
    try {
      issue = await this.github.getGithubIssue(
        payload.owner,
        payload.issueRepo,
        payload.issueNumber,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        kind: "fetch_failed",
        title: "Failed to fetch GitHub issue",
        description: message,
        analytics: {
          event: ANALYTICS_EVENTS.DEEP_LINK_ISSUE_FAILED,
          properties: {
            owner: payload.owner,
            repo: payload.issueRepo,
            issue_number: payload.issueNumber,
            reason: "fetch_failed",
            error_message: message,
          },
        },
      };
    }

    if (!issue) {
      return {
        kind: "not_found",
        title: "GitHub issue not found",
        description: `${payload.owner}/${payload.issueRepo}#${payload.issueNumber} could not be opened.`,
        analytics: {
          event: ANALYTICS_EVENTS.DEEP_LINK_ISSUE_FAILED,
          properties: {
            owner: payload.owner,
            repo: payload.issueRepo,
            issue_number: payload.issueNumber,
            reason: "not_found",
          },
        },
      };
    }

    const labelsText =
      issue.labels.length > 0 ? `\nLabels: ${issue.labels.join(", ")}` : "";
    const prompt = `GitHub Issue: ${issue.title}\n${issue.url}${labelsText}`;
    const cloudRepo = payload.repo ?? `${payload.owner}/${payload.issueRepo}`;

    return {
      kind: "navigate",
      navigation: {
        initialPrompt: prompt,
        initialCloudRepository: cloudRepo,
        initialModel: payload.model,
        initialMode: payload.mode,
      },
      analytics: {
        event: ANALYTICS_EVENTS.DEEP_LINK_ISSUE,
        properties: {
          owner: payload.owner,
          repo: payload.issueRepo,
          issue_number: payload.issueNumber,
          mode: payload.mode,
          model: payload.model,
        },
      },
    };
  }
}
