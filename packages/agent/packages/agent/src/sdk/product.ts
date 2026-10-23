/** Configures product behavior for an agent session. */
export interface AgentProduct {
  /** Stable product identifier. */
  readonly id: string;
  /** Configures behavior for one agent session. */
  configureSession(
    session: AgentSessionConfiguration,
  ): MaybePromise<SessionBehavior>;
}

/** Selects the product for a task run at application boot. */
export type ProductSelector = (
  launch: ProductLaunchConfiguration,
) => AgentProduct | undefined;

/** Behavior that applies for an agent session. */
export interface SessionBehavior {
  /** Instructions added to the identity section of the system prompt. */
  identityInstructions?: string;
  /** Instructions added to the result delivery section of the system prompt. */
  deliveryInstructions?: string;
  /** Instructions added at the end of the system prompt. */
  closingInstructions?: string;
  /** Surface that shows the agent replies. Sets the output formatting rules. */
  replySurface?: string;
  /** Pull request settings for the session. */
  pullRequests?: PullRequestOptions;
  /** Handles questions that the agent asks. */
  handleQuestions?(request: QuestionRequest): QuestionResponse;
}

/** Inputs and services for session configuration. */
export interface AgentSessionConfiguration<
  LaunchOptions extends object = Record<string, unknown>,
> {
  /** Task run data provided at launch. */
  readonly launch: ProductLaunchConfiguration<LaunchOptions>;
  /** Task-run operations available to the product. */
  readonly services: ProductServices;
}

/** Task run data passed to a product at launch. */
export interface ProductLaunchConfiguration<
  LaunchOptions extends object = Record<string, unknown>,
> {
  /** Task identifier. */
  readonly taskId: string;
  /** Task run identifier. */
  readonly runId: string;
  /** Product that started the run. */
  readonly originProduct?: string;
  /** Product-specific launch data. */
  readonly launchOptions: Readonly<LaunchOptions>;
  /** Optional source that started the task. */
  readonly source?: TaskSource;
}

/** A link to the source that started a task. */
export interface TaskSource {
  /** Source name, such as "inbox report". */
  readonly label: string;
  /** Source URL. */
  readonly url: string;
}

/** A request for answers to agent questions. */
export interface QuestionRequest {
  /** Questions from the agent. Empty when the question data is not valid. */
  readonly questions: readonly Question[];
}

/** One question from the agent. */
export interface Question {
  /** Question text. */
  readonly question: string;
  /** Available answer options. */
  readonly options?: ReadonlyArray<{ label: string; description?: string }>;
}

/** The answer the agent gets for its question tool call. */
export interface QuestionResponse {
  /** Message for the agent. */
  message: string;
  /** Skips the relay of the agent reply at the end of the turn when true. */
  awaitingReply: boolean;
}

/** Task-run operations available to products. */
export interface ProductServices {
  /** Sends a reply to the task source. The runtime reports delivery failures. */
  sendReply(reply: Reply): Promise<void>;
}

/** A reply sent to the task source. */
export interface Reply {
  /** Reply text. */
  message: string;
}

/** Pull request settings for a session. */
export interface PullRequestOptions {
  /** Publishes the pull request without an explicit request when true. */
  autoPublish?: boolean;
  /** Existing pull request URL. */
  existingUrl?: string | null;
  /** Footer line for pull request descriptions. */
  footer?: string;
}

export type MaybePromise<T> = T | Promise<T>;

export function defineProduct<LaunchOptions extends object>(definition: {
  readonly id: string;
  launchOptionsSchema: { parse(launchOptions: unknown): LaunchOptions };
  configureSession(
    session: AgentSessionConfiguration<LaunchOptions>,
  ): MaybePromise<SessionBehavior>;
}): AgentProduct {
  return {
    id: definition.id,
    configureSession(session) {
      const launchOptions = definition.launchOptionsSchema.parse(
        session.launch.launchOptions,
      );
      return definition.configureSession({
        ...session,
        launch: { ...session.launch, launchOptions },
      });
    },
  };
}

export function buildPullRequestFooter(
  launch: ProductLaunchConfiguration,
  options: { automated?: boolean; source?: TaskSource } = {},
): string {
  const mobile = launch.launchOptions.client_platform === "mobile";
  let createdWith =
    "Created with [PostHog Desktop](https://posthog.com/desktop?ref=pr)";
  if (mobile) {
    createdWith = "Created with [PostHog Mobile](https://posthog.com?ref=pr)";
  } else if (options.automated) {
    createdWith = "Created with [PostHog](https://posthog.com?ref=pr)";
  }

  const { source } = options;
  if (!source) {
    return `*${createdWith}*`;
  }
  const article = /^[aeiou]/i.test(source.label) ? "an" : "a";
  return `*${createdWith} from ${article} [${source.label}](${source.url})*`;
}
