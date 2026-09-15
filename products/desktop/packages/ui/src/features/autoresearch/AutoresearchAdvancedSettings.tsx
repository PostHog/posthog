import { SlidersHorizontal } from "@phosphor-icons/react";
import type { AutoresearchDraftConfig } from "@posthog/core/autoresearch/schemas";
import {
  Button,
  Field,
  FieldDescription,
  FieldLabel,
  FieldTitle,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Text,
} from "@posthog/quill";
import {
  type AutoresearchModelOption,
  StageEffortDropdown,
  StageModelSelect,
  stageValueLabel,
} from "./stageModels";

interface AutoresearchAdvancedSettingsProps {
  draft: AutoresearchDraftConfig;
  modelOptions: AutoresearchModelOption[];
  effortOptions: AutoresearchModelOption[];
  disabled: boolean;
  onChange: (patch: Partial<AutoresearchDraftConfig>) => void;
}

function stageSummary(
  model: string | null,
  effort: string | null,
  modelOptions: AutoresearchModelOption[],
  effortOptions: AutoresearchModelOption[],
): string {
  const modelLabel = stageValueLabel(model, modelOptions) ?? "task model";
  const effortLabel = stageValueLabel(effort, effortOptions);
  return effortLabel ? `${modelLabel} · ${effortLabel}` : modelLabel;
}

/** Optional stopping target and per-stage model controls, kept out of the main composer strip. */
export function AutoresearchAdvancedSettings({
  draft,
  modelOptions,
  effortOptions,
  disabled,
  onChange,
}: AutoresearchAdvancedSettingsProps) {
  const split =
    draft.implementModel !== draft.measureModel ||
    draft.implementEffort !== draft.measureEffort;
  const hasTarget = draft.targetValue !== null;

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            variant="link-muted"
            size="sm"
            disabled={disabled}
            aria-label="Advanced autoresearch settings"
          />
        }
      >
        <SlidersHorizontal />
        Advanced
        {(split || hasTarget) && <span aria-hidden>•</span>}
      </PopoverTrigger>
      <PopoverContent side="bottom" align="end" className="w-90">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <Text size="sm" weight="medium">
              Advanced settings
            </Text>
            <Text size="xs" variant="muted">
              Optional stopping and model controls.
            </Text>
          </div>

          <Field>
            <FieldLabel htmlFor="autoresearch-target">
              Stop early at this metric value
            </FieldLabel>
            <Input
              id="autoresearch-target"
              value={
                draft.targetValue === null ? "" : String(draft.targetValue)
              }
              onChange={(event) => {
                const raw = event.target.value.trim();
                const numeric = Number(raw);
                onChange({
                  targetValue:
                    raw === "" || !Number.isFinite(numeric) ? null : numeric,
                });
              }}
              placeholder="Optional"
              inputMode="decimal"
              aria-label="Target metric value to stop at"
              disabled={disabled}
            />
          </Field>

          <StageFields
            legend="Build improvements"
            description="Used to analyze the result and change the code."
            model={draft.implementModel}
            effort={draft.implementEffort}
            modelOptions={modelOptions}
            effortOptions={effortOptions}
            onModelChange={(value) => onChange({ implementModel: value })}
            onEffortChange={(value) => onChange({ implementEffort: value })}
          />
          <StageFields
            legend="Measure results"
            description="Used to run the measurement without changing code."
            model={draft.measureModel}
            effort={draft.measureEffort}
            modelOptions={modelOptions}
            effortOptions={effortOptions}
            onModelChange={(value) => onChange({ measureModel: value })}
            onEffortChange={(value) => onChange({ measureEffort: value })}
          />

          {split && (
            <Text size="xs" variant="muted">
              Build:{" "}
              {stageSummary(
                draft.implementModel,
                draft.implementEffort,
                modelOptions,
                effortOptions,
              )}
              . Measure:{" "}
              {stageSummary(
                draft.measureModel,
                draft.measureEffort,
                modelOptions,
                effortOptions,
              )}
              .
            </Text>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function StageFields({
  legend,
  description,
  model,
  effort,
  modelOptions,
  effortOptions,
  onModelChange,
  onEffortChange,
}: {
  legend: string;
  description: string;
  model: string | null;
  effort: string | null;
  modelOptions: AutoresearchModelOption[];
  effortOptions: AutoresearchModelOption[];
  onModelChange: (value: string | null) => void;
  onEffortChange: (value: string | null) => void;
}) {
  return (
    <Field>
      <FieldTitle>{legend}</FieldTitle>
      <FieldDescription>{description}</FieldDescription>
      <div className="flex gap-2">
        <StageModelSelect
          className="h-8! flex-1"
          ariaLabel={`${legend} model`}
          noneLabel="Task model"
          value={model}
          options={modelOptions}
          onChange={onModelChange}
        />
        {effortOptions.length > 0 && (
          <StageEffortDropdown
            className="h-8 w-28 justify-between"
            label={`${legend} effort`}
            noneLabel="Default effort"
            value={effort}
            options={effortOptions}
            onChange={onEffortChange}
          />
        )}
      </div>
    </Field>
  );
}
