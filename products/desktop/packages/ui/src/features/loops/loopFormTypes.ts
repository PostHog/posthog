import type { LoopSchemas } from "@posthog/api-client/loops";
import { systemTimezone } from "@posthog/ui/primitives/timezone";
import {
  buildSkillInstructions,
  type LoopSkillDraft,
  parseSkillContext,
  primaryLoopSkillBundle,
} from "./loopSkill";

/**
 * A trigger row in the create/edit form. `key` is a client-only stable
 * identity for list rendering (new rows have no server `id` yet); `id` is
 * only present once the trigger has been persisted, and is carried through
 * to the write payload so the backend updates the row in place instead of
 * creating a duplicate (see the Lifecycle section of the Loops spec on
 * id-stable trigger writes).
 */
export interface LoopTriggerDraft {
  key: string;
  id?: string;
  type: LoopSchemas.LoopTriggerTypeEnum;
  enabled: boolean;
  config: LoopSchemas.LoopTriggerConfig;
}

/** The context a loop is attached to in the form. `null` on `LoopFormValues.contextTarget`
 * means the loop isn't attached to any context. */
export interface LoopContextTargetDraft {
  folderId: string;
  name: string;
  outputs: LoopSchemas.LoopContextOutputs;
}

export interface LoopFormValues {
  name: string;
  description: string;
  visibility: LoopSchemas.LoopVisibilityEnum;
  instructions: string;
  /** When set, the loop runs this skill instead of free-form instructions;
   * `instructions` is derived as `/skill-name` plus `skillContext` on save. */
  skill: LoopSkillDraft | null;
  /** Optional free text appended after the skill invocation. Only meaningful
   * when `skill` is set. */
  skillContext: string;
  runtimeAdapter: LoopSchemas.LoopRuntimeAdapterEnum;
  model: string;
  reasoningEffort: LoopSchemas.LoopReasoningEffortEnum | null;
  /**
   * Full desired repository list. The form's picker only edits the first
   * entry; any additional entries are carried through untouched so saving an
   * unrelated change never drops a loop's other repository associations.
   */
  repositories: LoopSchemas.LoopRepositoryEntry[];
  /** MCP Store installation ids whose connections this loop's runs may use. */
  mcpInstallationIds: string[];
  /**
   * Passthrough, not edited by the form. The backend fills the default for a
   * missing `posthog_mcp_scopes` and deep-merges connectors on PATCH, so a
   * write that includes connectors must resend the loaded value or a custom
   * scope set via the API would be reset.
   */
  posthogMcpScopes: LoopSchemas.LoopPosthogMcpScopesEnum | null;
  triggers: LoopTriggerDraft[];
  behaviors: LoopSchemas.LoopBehaviors;
  notifications: LoopSchemas.LoopNotifications;
  contextTarget: LoopContextTargetDraft | null;
}

export function emptyLoopScheduleTriggerConfig(): LoopSchemas.LoopScheduleTriggerConfig {
  return { cron_expression: "0 9 * * 1", timezone: systemTimezone() };
}

export function emptyLoopGithubTriggerConfig(): LoopSchemas.LoopGithubTriggerConfig {
  return { github_integration_id: 0, repository: "", events: [] };
}

export function emptyLoopApiTriggerConfig(): LoopSchemas.LoopApiTriggerConfig {
  return {};
}

export function defaultLoopNotifications(): LoopSchemas.LoopNotifications {
  const off = { enabled: false, events: [], params: {} };
  return { push: { ...off }, email: { ...off }, slack: { ...off } };
}

export function defaultLoopBehaviors(): LoopSchemas.LoopBehaviors {
  return {
    create_prs: true,
    watch_ci: false,
    fix_review_comments: false,
    max_fix_iterations: 3,
  };
}

/** Sensible defaults when a loop is first attached to a context: file its runs into the
 * feed, but don't touch context.md or a canvas until the user opts in. */
export function defaultLoopContextOutputs(): LoopSchemas.LoopContextOutputs {
  return { post_to_feed: true, update_context: false, canvas_id: null };
}

/** The single "Auto-fix pull requests" toggle drives both CI-watching and
 * review-comment fixing; it reads as on only when both are on. */
export function isAutoFixEnabled(
  behaviors: LoopSchemas.LoopBehaviors,
): boolean {
  return behaviors.watch_ci && behaviors.fix_review_comments;
}

export function withAutoFix(
  behaviors: LoopSchemas.LoopBehaviors,
  enabled: boolean,
): LoopSchemas.LoopBehaviors {
  return { ...behaviors, watch_ci: enabled, fix_review_comments: enabled };
}

let draftKeySeq = 0;

export function nextDraftTriggerKey(): string {
  draftKeySeq += 1;
  return `draft-trigger-${draftKeySeq}`;
}

export function defaultLoopScheduleTrigger(): LoopTriggerDraft {
  return {
    key: nextDraftTriggerKey(),
    type: "schedule",
    enabled: true,
    config: emptyLoopScheduleTriggerConfig(),
  };
}

export function defaultLoopTriggerOfType(
  type: LoopSchemas.LoopTriggerTypeEnum,
): LoopTriggerDraft {
  if (type === "schedule") return defaultLoopScheduleTrigger();
  return {
    key: nextDraftTriggerKey(),
    type,
    enabled: true,
    config:
      type === "github"
        ? emptyLoopGithubTriggerConfig()
        : emptyLoopApiTriggerConfig(),
  };
}

export function emptyLoopFormValues(): LoopFormValues {
  return {
    name: "",
    description: "",
    visibility: "personal",
    instructions: "",
    skill: null,
    skillContext: "",
    runtimeAdapter: "claude",
    model: "",
    reasoningEffort: null,
    repositories: [],
    mcpInstallationIds: [],
    posthogMcpScopes: null,
    triggers: [defaultLoopScheduleTrigger()],
    behaviors: defaultLoopBehaviors(),
    notifications: defaultLoopNotifications(),
    contextTarget: null,
  };
}

/** A context-attached loop files its runs into the context's shared feed, so it must be
 * team-visible. The backend rejects personal + context; this keeps form state consistent
 * for prefills (e.g. "New loop" from a context page) and legacy loops. */
export function normalizeLoopFormValues(
  values: LoopFormValues,
): LoopFormValues {
  if (values.contextTarget && values.visibility !== "team") {
    return { ...values, visibility: "team" };
  }
  return values;
}

export function loopToFormValues(loop: LoopSchemas.Loop): LoopFormValues {
  const primaryBundle = primaryLoopSkillBundle(loop);
  return {
    name: loop.name,
    description: loop.description,
    visibility: loop.visibility,
    instructions: loop.instructions,
    skill: primaryBundle
      ? {
          kind: "attached",
          name: primaryBundle.skill_name,
          source: primaryBundle.skill_source,
        }
      : null,
    skillContext: primaryBundle
      ? parseSkillContext(loop.instructions, primaryBundle.skill_name)
      : "",
    runtimeAdapter: loop.runtime_adapter,
    model: loop.model,
    reasoningEffort: loop.reasoning_effort,
    repositories: [...loop.repositories],
    mcpInstallationIds: connectorInstallationIds(loop.connectors),
    posthogMcpScopes: loop.connectors?.posthog_mcp_scopes ?? null,
    triggers: loop.triggers.map((trigger) => ({
      key: trigger.id,
      id: trigger.id,
      type: trigger.type,
      enabled: trigger.enabled,
      config: trigger.config,
    })),
    behaviors: loop.behaviors,
    notifications: loop.notifications,
    contextTarget: loop.context_target
      ? {
          folderId: loop.context_target.folder_id,
          name: loop.context_target.name,
          outputs: loop.context_target.outputs,
        }
      : null,
  };
}

/** Defensive read of the backend-controlled connectors JSON: tolerate a
 * missing field, a non-array, or non-string entries rather than crashing the
 * form over one malformed loop. */
function connectorInstallationIds(
  connectors: LoopSchemas.LoopConnectors | null | undefined,
): string[] {
  const ids: unknown = connectors?.mcp_installation_ids;
  if (!Array.isArray(ids)) return [];
  return ids.filter((id): id is string => typeof id === "string");
}

/** Order-insensitive equality of two connector id selections. */
export function isSameConnectorSelection(a: string[], b: string[]): boolean {
  const aSet = new Set(a);
  const bSet = new Set(b);
  return aSet.size === bSet.size && [...aSet].every((id) => bSet.has(id));
}

export function formValuesToLoopWrite(
  values: LoopFormValues,
  options?: {
    /**
     * The backend deep-merges `connectors` on PATCH and validates the ids
     * against the owner's currently-active installations, so resending an
     * unchanged selection that contains a stale id would block an unrelated
     * edit. Updates pass false when the selection matches the loaded loop.
     */
    includeConnectors?: boolean;
  },
): LoopSchemas.LoopWrite {
  const connectors: LoopSchemas.LoopConnectorsWrite = {
    mcp_installation_ids: values.mcpInstallationIds,
    // See `LoopFormValues.posthogMcpScopes`: omitting the loaded scope would
    // let the backend's default overwrite it.
    ...(values.posthogMcpScopes
      ? { posthog_mcp_scopes: values.posthogMcpScopes }
      : {}),
  };
  return {
    name: values.name.trim(),
    description: values.description.trim(),
    visibility: values.visibility,
    instructions: values.skill
      ? buildSkillInstructions(values.skill.name, values.skillContext)
      : values.instructions,
    runtime_adapter: values.runtimeAdapter,
    model: values.model.trim(),
    reasoning_effort: values.reasoningEffort,
    repositories: values.repositories,
    ...(options?.includeConnectors === false ? {} : { connectors }),
    triggers: values.triggers.map((trigger) => ({
      id: trigger.id,
      type: trigger.type,
      enabled: trigger.enabled,
      config: trigger.config,
    })),
    behaviors: values.behaviors,
    notifications: values.notifications,
    context_target: values.contextTarget
      ? {
          folder_id: values.contextTarget.folderId,
          name: values.contextTarget.name,
          outputs: values.contextTarget.outputs,
        }
      : null,
  };
}

export function isLoopFormValid(values: LoopFormValues): boolean {
  if (!values.name.trim()) {
    return false;
  }
  if (!values.skill && !values.instructions.trim()) {
    return false;
  }
  if (values.contextTarget && values.visibility !== "team") {
    return false;
  }
  return values.triggers.every((trigger) => isTriggerDraftValid(trigger));
}

export function isTriggerDraftValid(trigger: LoopTriggerDraft): boolean {
  if (trigger.type === "schedule") {
    const config = trigger.config as LoopSchemas.LoopScheduleTriggerConfig;
    return !!config.run_at || !!config.cron_expression;
  }
  if (trigger.type === "github") {
    const config = trigger.config as LoopSchemas.LoopGithubTriggerConfig;
    return (
      !!config.repository &&
      config.github_integration_id > 0 &&
      config.events.length > 0
    );
  }
  return true;
}
