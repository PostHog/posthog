import type {
  NetworkAccessLevel,
  SandboxEnvironment,
  SandboxEnvironmentInput,
} from "@posthog/shared/domain-types";
import {
  DEFAULT_TOOL_IDS,
  IMAGE_PRESET_TOOLS,
  type ImagePresetTool,
  imagePresetBrief,
  imagePresetName,
} from "./imagePreset";
import {
  type ImageSpecInput,
  imageSpecError,
  setupCommandError,
} from "./imageSpec";

const DOMAIN_RE =
  /^(\*\.)?[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$/;

export function isValidDomain(domain: string): boolean {
  return DOMAIN_RE.test(domain);
}

export function validateDomains(text: string): {
  domains: string[];
  errors: string[];
} {
  const domains: string[] = [];
  const errors: string[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (isValidDomain(trimmed)) {
      domains.push(trimmed);
    } else {
      errors.push(`Invalid domain: ${trimmed}`);
    }
  }
  return { domains, errors };
}

/** Whether the flow creates an environment or adds to one that exists. */
export type SetupTarget = "new" | "existing";

/**
 * What the flow produces. An image scope creates only an image: it is reused by
 * any environment, so making one must not create an environment as a side
 * effect.
 */
export type SetupScope = "environment" | "image";

/** Where sessions in the environment start from. */
export type BaseImageChoice = "default" | "existing" | "new";

/**
 * A setup command with a stable id. Removing a line must not re-key the rest,
 * or the input being typed in loses focus.
 */
export interface SetupLine {
  id: string;
  value: string;
}

/** One environment variable, with a stable id so a row can be removed. */
export interface EnvVarRow {
  id: string;
  key: string;
  value: string;
}

export interface EnvironmentSetupPlan {
  scope: SetupScope;
  target: SetupTarget;
  /** The environment being added to, when the target is an existing one. */
  environmentId: string | null;
  environmentName: string;
  /** Set once the name is typed into, so the repository stops seeding it. */
  environmentNameEdited: boolean;
  /** Every repository this environment applies to; the first seeds the image. */
  repositories: readonly string[];
  private: boolean;
  networkAccessLevel: NetworkAccessLevel;
  allowedDomainsText: string;
  includeDefaultDomains: boolean;
  envVars: readonly EnvVarRow[];
  /**
   * False when custom images are unavailable (flag off or billing-disabled):
   * the image step disappears and the payload never carries an image id, so
   * the flow cannot walk someone into a build that fails at the end.
   */
  customImages: boolean;
  baseImage: BaseImageChoice;
  /** The image being reused, when the base image is an existing one. */
  existingImageId: string | null;
  imageName: string;
  imageNameEdited: boolean;
  excludedToolIds: readonly string[];
  setupLines: readonly SetupLine[];
}

export interface EmptyPlanOptions {
  repository?: string | null;
  scope?: SetupScope;
  /** False when custom images are unavailable to this account. */
  customImages?: boolean;
}

/**
 * The target always starts as a new environment: an existing one is a choice
 * the first step offers, and defaulting to it would open the flow on a
 * question with no answer yet.
 */
export function emptyEnvironmentSetupPlan({
  repository = null,
  scope = "environment",
  customImages = true,
}: EmptyPlanOptions = {}): EnvironmentSetupPlan {
  return {
    scope,
    target: "new",
    environmentId: null,
    environmentName: repository === null ? "" : environmentNameFor(repository),
    environmentNameEdited: false,
    repositories: repository === null ? [] : [repository],
    private: true,
    networkAccessLevel: "full",
    allowedDomainsText: "",
    includeDefaultDomains: true,
    envVars: [],
    customImages,
    baseImage: customImages && scope === "image" ? "new" : "default",
    existingImageId: null,
    imageName: repository === null ? "" : imagePresetName(repository),
    imageNameEdited: false,
    excludedToolIds: IMAGE_PRESET_TOOLS.filter(
      (tool) => !DEFAULT_TOOL_IDS.includes(tool.id),
    ).map((tool) => tool.id),
    setupLines: [],
  };
}

/**
 * The repository the image is built for. An environment can apply to several,
 * and setup commands run in one checkout, so the first is the one they use.
 */
export function primaryRepository(plan: EnvironmentSetupPlan): string | null {
  return plan.repositories[0] ?? null;
}

/**
 * An existing environment as a plan, so editing one uses the same fields the
 * setup flow does. Variable values are never returned by the API, so the rows
 * start empty and entering any replaces the whole set.
 */
export function planFromEnvironment(
  environment: SandboxEnvironment,
  { customImages = true }: { customImages?: boolean } = {},
): EnvironmentSetupPlan {
  return {
    scope: "environment",
    target: "existing",
    environmentId: environment.id,
    environmentName: environment.name,
    environmentNameEdited: true,
    repositories: environment.repositories,
    private: environment.private,
    networkAccessLevel: environment.network_access_level,
    allowedDomainsText: environment.allowed_domains.join("\n"),
    includeDefaultDomains: environment.include_default_domains,
    envVars: [],
    customImages,
    baseImage: environment.custom_image_id === null ? "default" : "existing",
    existingImageId: environment.custom_image_id,
    imageName: "",
    imageNameEdited: false,
    excludedToolIds: [],
    setupLines: [],
  };
}

/** The environment name suggested for a repository, e.g. `posthog cloud runs`. */
export function environmentNameFor(repository: string): string {
  const repoName = repository.split("/").pop() ?? repository;
  return `${repoName} cloud runs`;
}

/**
 * Both names follow the first repository until they are typed into, so the
 * common path needs no typing and a chosen name is never overwritten.
 */
export function withRepositories(
  plan: EnvironmentSetupPlan,
  repositories: readonly string[],
): EnvironmentSetupPlan {
  const primary = repositories[0] ?? null;
  if (primary === null) return { ...plan, repositories };
  return {
    ...plan,
    repositories,
    environmentName: plan.environmentNameEdited
      ? plan.environmentName
      : environmentNameFor(primary),
    imageName: plan.imageNameEdited ? plan.imageName : imagePresetName(primary),
  };
}

export function withEnvironmentName(
  plan: EnvironmentSetupPlan,
  environmentName: string,
): EnvironmentSetupPlan {
  return { ...plan, environmentName, environmentNameEdited: true };
}

export function withImageName(
  plan: EnvironmentSetupPlan,
  imageName: string,
): EnvironmentSetupPlan {
  return { ...plan, imageName, imageNameEdited: true };
}

export function withToolToggled(
  plan: EnvironmentSetupPlan,
  toolId: string,
): EnvironmentSetupPlan {
  return {
    ...plan,
    excludedToolIds: plan.excludedToolIds.includes(toolId)
      ? plan.excludedToolIds.filter((id) => id !== toolId)
      : [...plan.excludedToolIds, toolId],
  };
}

export function planTools(plan: EnvironmentSetupPlan): ImagePresetTool[] {
  return IMAGE_PRESET_TOOLS.filter(
    (tool) => !plan.excludedToolIds.includes(tool.id),
  );
}

export function planSetupCommands(plan: EnvironmentSetupPlan): string[] {
  return plan.setupLines
    .map((line) => line.value)
    .filter((command) => command.trim() !== "");
}

export function planSpecInput(plan: EnvironmentSetupPlan): ImageSpecInput {
  return {
    tools: planTools(plan),
    setupCommands: planSetupCommands(plan),
    repository: primaryRepository(plan),
  };
}

/** True when the flow will author and build a new image. */
export function buildsImage(plan: EnvironmentSetupPlan): boolean {
  return plan.baseImage === "new";
}

export type SetupStepKey =
  | "environment"
  | "access"
  | "image"
  | "tools"
  | "setup"
  | "review";

const STEP_LABELS: Record<SetupStepKey, string> = {
  environment: "Environment",
  access: "Access",
  image: "Image",
  tools: "Tools",
  setup: "Setup",
  review: "Review",
};

export interface SetupStep {
  key: SetupStepKey;
  label: string;
}

/**
 * The steps this plan actually has. An existing environment keeps its own
 * access settings, and setup commands only exist for an image being built, so
 * neither step is shown as a dead end.
 */
export function setupSteps(plan: EnvironmentSetupPlan): SetupStep[] {
  if (plan.scope === "image") {
    return (["image", "tools", "setup", "review"] as SetupStepKey[]).map(
      (key) => ({ key, label: STEP_LABELS[key] }),
    );
  }
  const keys: SetupStepKey[] = ["environment"];
  if (plan.target === "new") keys.push("access");
  if (plan.customImages) keys.push("image");
  if (buildsImage(plan)) keys.push("tools", "setup");
  keys.push("review");
  return keys.map((key) => ({
    key,
    label: key === "image" ? "Base image" : STEP_LABELS[key],
  }));
}

const ENV_KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

/**
 * Keys the environment API refuses, mirrored from RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS
 * in products/tasks/backend/constants.py. The server stays the last word; this copy
 * lets the row show its error before submit.
 */
const RESERVED_ENV_VAR_KEYS: ReadonlySet<string> = new Set([
  "POSTHOG_PERSONAL_API_KEY",
  "POSTHOG_WIZARD_API_KEY",
  "POSTHOG_API_URL",
  "POSTHOG_PROJECT_ID",
  "JWT_PUBLIC_KEY",
  "GITHUB_TOKEN",
  "GH_TOKEN",
  "LLM_GATEWAY_URL",
  "AI_GATEWAY_URL",
  "AI_GATEWAY_PRODUCTS",
  "AI_GATEWAY_TOKEN",
  "POSTHOG_RESUME_RUN_ID",
  "POSTHOG_AGENT_OTEL_LOGS_URL",
  "POSTHOG_AGENT_OTEL_LOGS_TOKEN",
  "POSTHOG_AGENT_OTEL_TRACES_URL",
  "POSTHOG_IMAGE_TOOLS",
  "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
  "DISABLE_TELEMETRY",
  "DISABLE_ERROR_REPORTING",
  "POSTHOG_CONTEXT_LAYER_PATH",
  "POSTHOG_CONTEXT_LAYER_COMMITS_PATH",
]);

/** BLOCKED_SANDBOX_ENVIRONMENT_VARIABLE_PREFIXES in the same file; same mirror rule. */
const BLOCKED_ENV_VAR_PREFIXES = ["LD_", "DYLD_", "GIT_"] as const;

/** BLOCKED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS in the same file; same mirror rule. */
const BLOCKED_ENV_VAR_KEYS: ReadonlySet<string> = new Set([
  "NODE_OPTIONS",
  "NODE_REPL_EXTERNAL_MODULE",
  "BASH_ENV",
  "PROMPT_COMMAND",
  "PYTHONSTARTUP",
  "PERL5OPT",
  "RUBYOPT",
]);

/** Why one row cannot be sent, or null when it is fine. */
export function envVarError(
  row: EnvVarRow,
  rows: readonly EnvVarRow[],
): string | null {
  const key = row.key.trim();
  if (key === "") return row.value.trim() === "" ? null : "Name this variable.";
  if (!ENV_KEY_RE.test(key)) {
    return "Letters, digits and underscores only, and not starting with a digit.";
  }
  if (RESERVED_ENV_VAR_KEYS.has(key)) {
    return `${key} is reserved by PostHog and cannot be set.`;
  }
  if (
    BLOCKED_ENV_VAR_KEYS.has(key) ||
    BLOCKED_ENV_VAR_PREFIXES.some((prefix) => key.startsWith(prefix))
  ) {
    return `${key} can change how sandbox processes execute code, so it is not allowed.`;
  }
  const duplicate = rows.some(
    (other) => other.id !== row.id && other.key.trim() === key,
  );
  return duplicate ? `${key} is set twice.` : null;
}

/**
 * Splits pasted text into rows. A pasted .env file, a shell export block or a
 * single KEY=value all land the same way, since that is how people carry these
 * between machines.
 */
export function parseEnvVarText(
  text: string,
): { key: string; value: string }[] {
  const rows: { key: string; value: string }[] = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim().replace(/^export\s+/, "");
    if (trimmed === "" || trimmed.startsWith("#")) continue;
    const separator = trimmed.indexOf("=");
    if (separator <= 0) continue;
    const key = trimmed.slice(0, separator).trim();
    let value = trimmed.slice(separator + 1).trim();
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    rows.push({ key, value });
  }
  return rows;
}

/** The rows that carry a variable, ignoring blank ones left behind. */
export function filledEnvVars(plan: EnvironmentSetupPlan): EnvVarRow[] {
  return plan.envVars.filter((row) => row.key.trim() !== "");
}

/** Why a step is unresolved, or null when it is done. */
export function stepError(
  plan: EnvironmentSetupPlan,
  key: SetupStepKey,
): string | null {
  switch (key) {
    case "environment":
      if (plan.target === "existing") {
        return plan.environmentId === null
          ? "Pick the environment to add to."
          : null;
      }
      return plan.environmentName.trim() === ""
        ? "Give the environment a name."
        : null;

    case "access": {
      if (plan.networkAccessLevel === "custom") {
        const domains = validateDomains(plan.allowedDomainsText);
        if (domains.errors[0]) return domains.errors[0];
        if (domains.domains.length === 0) {
          return "Add a domain, or pick another access level.";
        }
      }
      for (const row of plan.envVars) {
        const error = envVarError(row, plan.envVars);
        if (error) return error;
      }
      return null;
    }

    case "image":
      if (plan.scope === "image") {
        return plan.imageName.trim() === "" ? "Give the image a name." : null;
      }
      if (plan.baseImage === "existing") {
        return plan.existingImageId === null ? "Pick an image." : null;
      }
      if (plan.baseImage === "new" && plan.imageName.trim() === "") {
        return "Give the image a name.";
      }
      return null;

    case "tools":
      return imageSpecError(planSpecInput(plan));

    case "setup": {
      for (const command of planSetupCommands(plan)) {
        const error = setupCommandError(command);
        if (error) return error;
      }
      return null;
    }

    case "review": {
      for (const step of setupSteps(plan)) {
        if (step.key === "review") continue;
        const error = stepError(plan, step.key);
        if (error) return error;
      }
      return null;
    }
  }
}

/** Per-step completeness, in the order `setupSteps` returns. */
export function setupStepsComplete(plan: EnvironmentSetupPlan): boolean[] {
  return setupSteps(plan).map((step) => stepError(plan, step.key) === null);
}

/**
 * The environment payload this plan creates. The repositories are carried so
 * the environment records what it is for, which is also how the cost checklist
 * sees that an image is in use.
 */
export function planEnvironmentInput(
  plan: EnvironmentSetupPlan,
  customImageId: string | null,
): SandboxEnvironmentInput {
  const isCustom = plan.networkAccessLevel === "custom";
  const envVars = filledEnvVars(plan);
  return {
    name: plan.environmentName.trim(),
    network_access_level: plan.networkAccessLevel,
    allowed_domains: isCustom
      ? validateDomains(plan.allowedDomainsText).domains
      : [],
    include_default_domains: isCustom ? plan.includeDefaultDomains : false,
    private: plan.private,
    repositories: [...plan.repositories],
    // Accounts without custom images must not send the key at all: the API
    // rejects it when the feature is billing-disabled.
    ...(plan.customImages ? { custom_image_id: customImageId } : {}),
    ...(envVars.length > 0
      ? {
          environment_variables: Object.fromEntries(
            envVars.map((row) => [row.key.trim(), row.value]),
          ),
        }
      : {}),
  };
}

export interface ImageCreateInput {
  name: string;
  description: string;
  repository?: string;
  private?: boolean;
}

/** The creation payload for the image this plan builds. */
export function planImageInput(plan: EnvironmentSetupPlan): ImageCreateInput {
  const repository = primaryRepository(plan);
  return {
    name: plan.imageName.trim(),
    description: imagePresetBrief(
      repository,
      planTools(plan),
      planSetupCommands(plan),
    ),
    ...(repository ? { repository } : {}),
    ...(plan.private ? { private: true } : {}),
  };
}

function sameArray<T>(
  a: readonly T[],
  b: readonly T[],
  same: (x: T, y: T) => boolean = (x, y) => x === y,
): boolean {
  return (
    a.length === b.length && a.every((item, index) => same(item, b[index]))
  );
}

/** Whether the plan differs from the saved one, compared field by field. */
export function isPlanDirty(
  plan: EnvironmentSetupPlan,
  saved: EnvironmentSetupPlan,
): boolean {
  return !(
    plan.scope === saved.scope &&
    plan.target === saved.target &&
    plan.environmentId === saved.environmentId &&
    plan.environmentName === saved.environmentName &&
    plan.environmentNameEdited === saved.environmentNameEdited &&
    sameArray(plan.repositories, saved.repositories) &&
    plan.private === saved.private &&
    plan.networkAccessLevel === saved.networkAccessLevel &&
    plan.allowedDomainsText === saved.allowedDomainsText &&
    plan.includeDefaultDomains === saved.includeDefaultDomains &&
    sameArray(
      plan.envVars,
      saved.envVars,
      (x, y) => x.id === y.id && x.key === y.key && x.value === y.value,
    ) &&
    plan.customImages === saved.customImages &&
    plan.baseImage === saved.baseImage &&
    plan.existingImageId === saved.existingImageId &&
    plan.imageName === saved.imageName &&
    plan.imageNameEdited === saved.imageNameEdited &&
    sameArray(plan.excludedToolIds, saved.excludedToolIds) &&
    sameArray(
      plan.setupLines,
      saved.setupLines,
      (x, y) => x.id === y.id && x.value === y.value,
    )
  );
}
