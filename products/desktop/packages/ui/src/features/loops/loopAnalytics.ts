import type {
  LoopEnabledToggledProperties,
  LoopSavedProperties,
  LoopViewedProperties,
} from "@posthog/shared/analytics-events";
import type { LoopSchemas } from "@posthog/ui/features/loops/loopSchemas";

function triggerFlags(triggers: LoopSchemas.Loop["triggers"]) {
  return {
    trigger_count: triggers.length,
    has_schedule_trigger: triggers.some(
      (trigger) => trigger.type === "schedule",
    ),
    has_github_trigger: triggers.some((trigger) => trigger.type === "github"),
  };
}

export function buildLoopViewedProps(
  loop: LoopSchemas.Loop,
  recentRunCount: number,
): LoopViewedProperties {
  return {
    loop_id: loop.id,
    enabled: loop.enabled,
    model: loop.model || undefined,
    reasoning_effort: loop.reasoning_effort,
    repository_count: loop.repositories.length,
    ...triggerFlags(loop.triggers),
    last_run_status: loop.last_run_status,
    recent_run_count: recentRunCount,
  };
}

export function buildLoopSavedProps(
  loop: LoopSchemas.Loop,
): LoopSavedProperties {
  return {
    loop_id: loop.id,
    model: loop.model || undefined,
    reasoning_effort: loop.reasoning_effort,
    repository_count: loop.repositories.length,
    ...triggerFlags(loop.triggers),
    notification_channel_count: (["email", "slack"] as const).filter(
      (channel) => loop.notifications[channel].enabled,
    ).length,
    has_context_target: loop.context_target !== null,
  };
}

export function buildLoopEnabledToggledProps(
  loop: LoopSchemas.Loop,
  enabled: boolean,
  success: boolean,
): LoopEnabledToggledProperties {
  return { loop_id: loop.id, enabled, success };
}
