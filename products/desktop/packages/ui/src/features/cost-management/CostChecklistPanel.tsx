import { ArrowRight, Check } from "@phosphor-icons/react";
import type { CostChecklistItem } from "@posthog/core/billing/costChecklist";
import { leanSkillById } from "@posthog/core/billing/leanSkills";
import { modelCostInfo } from "@posthog/core/billing/modelPricing";
import { Button, Text } from "@posthog/quill";
import { formatModelId } from "@posthog/shared";
import { modelCostTitle } from "@posthog/ui/features/sessions/components/ModelCostChip";
import type { ReactNode } from "react";

interface CostChecklistPanelProps {
  items: CostChecklistItem[];
  onSwitchModel: (toModelId: string) => void;
  onCreateImage: () => void;
  onInstallSkill: (skillId: string) => void;
  onUninstallSkill: (skillId: string) => void;
  /** Opens one skill's details, with its links. */
  onOpenSkill: (skillId: string) => void;
  /** The skills an install or removal is in flight for. */
  busySkillIds: ReadonlySet<string>;
}

/**
 * The recommendation checklist. Each row is a change worth making with the
 * button that makes it; a row that has been acted on stays as a muted record
 * at the bottom. There is no dismiss.
 */
export function CostChecklistPanel({
  items,
  onSwitchModel,
  onCreateImage,
  onInstallSkill,
  onUninstallSkill,
  onOpenSkill,
  busySkillIds,
}: CostChecklistPanelProps) {
  if (items.length === 0) {
    return (
      <div className="rounded-(--radius-3) border border-(--gray-5) border-dashed px-4 py-3.5">
        <Text className="text-(--gray-11) text-[12.5px]">
          Nothing to change right now. New suggestions show up here when your
          setup has something worth changing.
        </Text>
      </div>
    );
  }

  const allDone = items.every((item) => item.done);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col divide-y divide-(--gray-4) overflow-hidden rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid)">
        {items.map((item) => (
          <ChecklistRow
            key={
              item.kind === "install-skill"
                ? `${item.kind}:${item.skillId}`
                : item.kind
            }
            done={item.done}
            {...rowContent(item, {
              onSwitchModel,
              onCreateImage,
              onInstallSkill,
              onUninstallSkill,
              onOpenSkill,
              busySkillIds,
            })}
          />
        ))}
      </div>
      {allDone && (
        <Text className="px-1 text-(--gray-10) text-[11.5px]">
          Everything here is checked off.
        </Text>
      )}
    </div>
  );
}

interface RowHandlers {
  onSwitchModel: (toModelId: string) => void;
  onCreateImage: () => void;
  onInstallSkill: (skillId: string) => void;
  onUninstallSkill: (skillId: string) => void;
  onOpenSkill: (skillId: string) => void;
  busySkillIds: ReadonlySet<string>;
}

interface RowContent {
  title: string;
  detail: ReactNode;
  action: ReactNode;
}

function rowContent(item: CostChecklistItem, h: RowHandlers): RowContent {
  switch (item.kind) {
    case "model-notch":
      return item.done
        ? {
            title: "Default model moved down a notch",
            detail: (
              <span className="flex flex-wrap items-center gap-1.5">
                New sessions start on
                <ModelChip modelId={item.modelId} emphasis />
              </span>
            ),
            action: null,
          }
        : {
            title: "Move your default model one notch down",
            detail: (
              <span className="flex flex-col gap-1.5">
                <span className="flex flex-wrap items-center gap-1.5">
                  <ModelChip modelId={item.fromModelId} />
                  <ArrowRight
                    size={11}
                    className="text-(--gray-9)"
                    aria-hidden="true"
                  />
                  <ModelChip modelId={item.toModelId} emphasis />
                </span>
                <span>
                  The next step down your capability ladder. New sessions only,
                  so open sessions keep the model they are on.
                </span>
              </span>
            ),
            action: (
              <Button
                variant="outline"
                size="sm"
                data-attr="cost-management-switch-default-model"
                onClick={() => h.onSwitchModel(item.toModelId)}
              >
                Switch default
              </Button>
            ),
          };

    case "custom-image":
      return item.done
        ? {
            title: "Custom sandbox image built",
            detail:
              "Pick it as the base image of a cloud environment to start runs from it.",
            action: null,
          }
        : {
            title: "Build a custom sandbox image",
            detail:
              "Cloud runs start from your dependencies and a lean set of search tools instead of installing them each time.",
            action: (
              <Button
                variant="outline"
                size="sm"
                data-attr="cost-management-open-image-preset"
                onClick={() => h.onCreateImage()}
              >
                Build image
              </Button>
            ),
          };

    case "install-skill": {
      const skill = leanSkillById(item.skillId);
      const busy = h.busySkillIds.has(item.skillId);
      const details = (
        <button
          type="button"
          className="text-(--gray-12) underline decoration-(--gray-7)"
          onClick={() => h.onOpenSkill(item.skillId)}
        >
          Details
        </button>
      );
      return {
        title: item.name,
        detail: (
          <span className="flex flex-wrap items-center gap-x-2">
            {skill?.summary ?? ""}
            {details}
          </span>
        ),
        action: item.done ? (
          <Button
            variant="link-muted"
            size="sm"
            loading={busy}
            disabled={busy}
            data-attr="cost-management-uninstall-lean-skill"
            onClick={() => h.onUninstallSkill(item.skillId)}
          >
            Uninstall
          </Button>
        ) : (
          <Button
            variant="outline"
            size="sm"
            loading={busy}
            disabled={busy}
            data-attr="cost-management-install-lean-skill"
            onClick={() => h.onInstallSkill(item.skillId)}
          >
            Install
          </Button>
        ),
      };
    }
  }
}

function ChecklistRow({
  done,
  title,
  detail,
  action,
}: RowContent & { done: boolean }) {
  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 ${done ? "opacity-65" : ""}`}
    >
      <span
        aria-hidden="true"
        className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full ${
          done ? "bg-(--gray-12) text-(--gray-1)" : "border border-(--gray-7)"
        }`}
      >
        {done && <Check size={10} weight="bold" />}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Text
          className={`text-[12.5px] ${done ? "font-normal text-(--gray-11)" : "font-medium text-(--gray-12)"}`}
        >
          {title}
        </Text>
        <Text className="text-(--gray-11) text-[11.5px] leading-snug">
          {detail}
        </Text>
      </div>
      {action && <span className="shrink-0 pt-0.5">{action}</span>}
    </div>
  );
}

/** A model with its per-token multiplier, matching the picker's chips. */
function ModelChip({
  modelId,
  emphasis = false,
}: {
  modelId: string;
  emphasis?: boolean;
}) {
  const cost = modelCostInfo(modelId);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-(--radius-2) bg-(--gray-3) px-1.5 py-0.5 ${
        emphasis ? "text-(--gray-12)" : "text-(--gray-11)"
      }`}
      title={modelCostTitle(modelId)}
    >
      <span className={`text-[11px] ${emphasis ? "font-medium" : ""}`}>
        {formatModelId(modelId)}
      </span>
      {cost && (
        <span className="text-(--gray-10) text-[10px] tabular-nums">
          {cost.multiplierLabel}
        </span>
      )}
    </span>
  );
}
