export interface GithubPrTitleClient {
  getGithubPullRequestTitle(input: {
    owner: string;
    repo: string;
    number: number;
  }): Promise<string | null>;
}

export interface TitleGeneratorLogger {
  error(message: string, data?: unknown): void;
}

export const TITLE_GENERATOR_SERVICE = Symbol.for(
  "posthog.core.sessions.titleGeneratorService",
);
export const TITLE_GENERATOR_GITHUB_PR_TITLE_CLIENT = Symbol.for(
  "posthog.core.sessions.titleGeneratorGithubPrTitleClient",
);
export const TITLE_GENERATOR_LOGGER = Symbol.for(
  "posthog.core.sessions.titleGeneratorLogger",
);
