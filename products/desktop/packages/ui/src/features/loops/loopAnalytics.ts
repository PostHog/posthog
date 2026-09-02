import type { LoopSchemas } from "@posthog/api-client/loops";
import type {
  LoopEnabledToggledProperties,
  LoopSavedProperties,
  LoopViewedProperties,
} from "@posthog/shared/analytics-events";
import { isAutoFixEnabled } from "./loopFormTypes";

function triggerFlags(triggers: LoopSchemas.Loop["triggers"]) {
  return {
    trigger_count: triggers.length,
    has_schedule_trigger: triggers.some(
      (trigger) => trigger.type === "schedule",
    ),
    has_github_trigger: triggers.some((trigger) => trigger.type === "github"),
    has_api_trigger: triggers.some((trigger) => trigger.type === "api"),
  };
}

export function buildLoopViewedProps(
  loop: LoopSchemas.Loop,
  recentRunCount: number,
): LoopViewedProperties {
  return {
    loop_id: loop.id,
    visibility: loop.visibility,
    enabled: loop.enabled,
    disabled_reason: loop.disabled_reason,
    runtime_adapter: loop.runtime_adapter,
    model: loop.model || undefined,
    reasoning_effort: loop.reasoning_effort,
    repository_count: loop.repositories.length,
    ...triggerFlags(loop.triggers),
    last_run_status: loop.last_run_status,
    consecutive_failures: loop.consecutive_failures,
    recent_run_count: recentRunCount,
  };
}

export function buildLoopSavedProps(
  loop: LoopSchemas.Loop,
): LoopSavedProperties {
  return {
    loop_id: loop.id,
    visibility: loop.visibility,
    runtime_adapter: loop.runtime_adapter,
    model: loop.model || undefined,
    reasoning_effort: loop.reasoning_effort,
    repository_count: loop.repositories.length,
    ...triggerFlags(loop.triggers),
    is_pr_creation_enabled: loop.behaviors.create_prs,
    is_auto_fix_enabled: isAutoFixEnabled(loop.behaviors),
    notification_channel_count: (["push", "email", "slack"] as const).filter(
      (channel) => loop.notifications[channel]?.enabled,
    ).length,
    has_context_target: loop.context_target !== null,
  };
}

export function buildLoopEnabledToggledProps(
  loop: LoopSchemas.Loop,
  enabled: boolean,
  success: boolean,
): LoopEnabledToggledProperties {
  return {
    loop_id: loop.id,
    enabled,
    visibility: loop.visibility,
    was_auto_paused: loop.disabled_reason !== null,
    success,
  };
}
