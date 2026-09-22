import type { LoopSchemas } from "@posthog/api-client/loops";

/** What the loop's backend can store. Workflow-backed loops carry one trigger,
 * subscribe to one GitHub event type, and have no payload conditions. */
export interface LoopTriggerEditorLimits {
  triggerTypes: LoopSchemas.LoopTriggerTypeEnum[];
  maxTriggers: number | null;
  singleGithubEvent: boolean;
  githubPayloadConditions: boolean;
}

export const LOOPS_API_TRIGGER_LIMITS: LoopTriggerEditorLimits = {
  triggerTypes: ["schedule", "github", "api"],
  maxTriggers: null,
  singleGithubEvent: false,
  githubPayloadConditions: true,
};

export const WORKFLOW_TRIGGER_LIMITS: LoopTriggerEditorLimits = {
  triggerTypes: ["schedule", "github"],
  maxTriggers: 1,
  singleGithubEvent: true,
  githubPayloadConditions: false,
};
