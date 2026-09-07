import { ClockIcon, PauseIcon, WarningIcon } from "@phosphor-icons/react";
import {
  deriveScoutLifecycle,
  type ScoutAttention,
  type ScoutAttentionKind,
  scoutSkillSlug,
} from "@posthog/core/scouts/scoutPresentation";
import { Badge, Button } from "@posthog/quill";
import { useAgentsPageActions } from "@posthog/ui/features/agents/agentsPageStore";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { AgentNameLink } from "./AgentNameLink";

const MAX_CARDS = 3;

const KIND_META: Record<
  ScoutAttentionKind,
  { label: string; tone: "warning" | "destructive"; Icon: typeof PauseIcon }
> = {
  auto_paused: { label: "Auto-paused", tone: "warning", Icon: PauseIcon },
  failing: { label: "Failing", tone: "destructive", Icon: WarningIcon },
  pausing_soon: { label: "Pausing soon", tone: "warning", Icon: ClockIcon },
};

/**
 * The agents that need a person before anything else, each with the one
 * action that resolves it. Renders nothing when the fleet is healthy.
 */
export function ScoutAttentionStrip({
  items,
  onUpdateConfig,
}: {
  items: ScoutAttention[];
  onUpdateConfig: (configId: string, updates: ScoutConfigUpdate) => void;
}) {
  const { openAgent } = useAgentsPageActions();
  const shown = items.slice(0, MAX_CARDS);
  const hidden = items.length - shown.length;

  return (
    <div className="flex flex-col gap-2">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map(({ kind, config, detail }) => {
          const { label, tone, Icon } = KIND_META[kind];
          const slug = scoutSkillSlug(config.skill_name);
          const lifecycle = deriveScoutLifecycle(config);
          const iconTone =
            tone === "destructive" ? "text-(--red-11)" : "text-(--amber-11)";
          return (
            <div
              key={config.id}
              className="flex gap-3 rounded-(--radius-md) border border-border bg-(--color-panel-solid) px-3.5 py-3"
            >
              <Icon size={16} className={`mt-0.5 shrink-0 ${iconTone}`} />
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex min-w-0 items-center gap-2">
                  <AgentNameLink
                    config={config}
                    onOpen={() => openAgent(slug)}
                  />
                  <Badge variant={tone}>{label}</Badge>
                </div>
                <p className="line-clamp-2 text-[11.5px] text-gray-10 leading-snug">
                  {detail}
                </p>
                <div className="mt-1.5 flex items-center gap-1.5">
                  {kind === "auto_paused" ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="xs"
                      onClick={() =>
                        onUpdateConfig(config.id, { enabled: true })
                      }
                      data-attr="scout-attention-resume"
                    >
                      Resume
                    </Button>
                  ) : null}
                  {kind === "pausing_soon" &&
                  lifecycle.autoPauseExempt === false ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="xs"
                      onClick={() =>
                        onUpdateConfig(config.id, { auto_pause_exempt: true })
                      }
                      data-attr="scout-attention-keep-running"
                    >
                      Keep running
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    onClick={() => openAgent(slug, { tab: "activity" })}
                    data-attr="scout-attention-open-runs"
                  >
                    {kind === "failing" ? "Open last run" : "Review runs"}
                  </Button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {hidden > 0 ? (
        <p className="text-[11.5px] text-gray-10">
          {hidden} more agent{hidden === 1 ? "" : "s"} need
          {hidden === 1 ? "s" : ""} attention. Select All and clear the table
          filters to find them.
        </p>
      ) : null}
    </div>
  );
}
