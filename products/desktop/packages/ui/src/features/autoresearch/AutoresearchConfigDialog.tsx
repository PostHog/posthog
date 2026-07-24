import type { AutoresearchDirection } from "@posthog/core/autoresearch/schemas";
import {
  Button,
  Dialog,
  Flex,
  Select,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import { useState } from "react";
import {
  type AutoresearchModelOption,
  clampMaxIterations,
  StageModelSelect,
} from "./stageModels";

export type { AutoresearchModelOption };

export interface AutoresearchConfigValues {
  direction: AutoresearchDirection;
  targetValue: number | null;
  maxIterations: number;
  implementModel: string | null;
  measureModel: string | null;
  implementEffort: string | null;
  measureEffort: string | null;
  instructions?: string;
}

interface AutoresearchConfigDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  submitLabel: string;
  /** Show the instructions field (dashboard re-runs); the create-task flow takes instructions from the composer prompt instead. */
  showInstructions?: boolean;
  /** Session model options for the stage-model selects; hidden when empty. */
  modelOptions?: AutoresearchModelOption[];
  /** Session effort options for the stage-effort selects; hidden when empty. */
  effortOptions?: AutoresearchModelOption[];
  initial?: Partial<AutoresearchConfigValues>;
  /** May throw. The message is shown inline and the dialog stays open. */
  onSubmit: (values: AutoresearchConfigValues) => void;
}

export function AutoresearchConfigDialog({
  open,
  onOpenChange,
  title,
  description,
  submitLabel,
  showInstructions = false,
  modelOptions = [],
  effortOptions = [],
  initial,
  onSubmit,
}: AutoresearchConfigDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="480px" size="2">
        <Dialog.Title className="text-base">{title}</Dialog.Title>
        <Dialog.Description className="text-sm" color="gray">
          {description}
        </Dialog.Description>
        {/* Radix unmounts closed dialog content, so the form mounts fresh
            (seeded from the current `initial`) on every open. */}
        <ConfigForm
          submitLabel={submitLabel}
          showInstructions={showInstructions}
          modelOptions={modelOptions}
          effortOptions={effortOptions}
          initial={initial}
          onSubmit={onSubmit}
          onDone={() => onOpenChange(false)}
        />
      </Dialog.Content>
    </Dialog.Root>
  );
}

interface FormValues {
  direction: AutoresearchDirection;
  targetValue: string;
  maxIterations: string;
  implementModel: string | null;
  measureModel: string | null;
  implementEffort: string | null;
  measureEffort: string | null;
  instructions: string;
}

function ConfigForm({
  submitLabel,
  showInstructions,
  modelOptions,
  effortOptions,
  initial,
  onSubmit,
  onDone,
}: {
  submitLabel: string;
  showInstructions: boolean;
  modelOptions: AutoresearchModelOption[];
  effortOptions: AutoresearchModelOption[];
  initial?: Partial<AutoresearchConfigValues>;
  onSubmit: (values: AutoresearchConfigValues) => void;
  onDone: () => void;
}) {
  const [values, setValues] = useState<FormValues>(() => ({
    direction: initial?.direction ?? "maximize",
    targetValue:
      initial?.targetValue != null ? String(initial.targetValue) : "",
    maxIterations: String(initial?.maxIterations ?? 10),
    implementModel: initial?.implementModel ?? null,
    measureModel: initial?.measureModel ?? null,
    implementEffort: initial?.implementEffort ?? null,
    measureEffort: initial?.measureEffort ?? null,
    instructions: initial?.instructions ?? "",
  }));
  const [error, setError] = useState<string | null>(null);

  const setField = <K extends keyof FormValues>(
    field: K,
    value: FormValues[K],
  ) => setValues((current) => ({ ...current, [field]: value }));

  const canSubmit = !showInstructions || values.instructions.trim().length > 0;

  const handleSubmit = () => {
    const target =
      values.targetValue.trim() === "" ? null : Number(values.targetValue);
    if (target !== null && !Number.isFinite(target)) {
      setError("Target must be a number.");
      return;
    }
    const iterations = Number.parseInt(values.maxIterations, 10);
    try {
      onSubmit({
        direction: values.direction,
        targetValue: target,
        maxIterations: clampMaxIterations(iterations),
        implementModel: values.implementModel,
        measureModel: values.measureModel,
        implementEffort: values.implementEffort,
        measureEffort: values.measureEffort,
        instructions: showInstructions ? values.instructions : undefined,
      });
      setError(null);
      onDone();
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Failed to apply the configuration.",
      );
    }
  };

  return (
    <>
      <Flex direction="column" gap="3" mt="4">
        <Flex gap="3">
          <div className="flex-1">
            <Text
              as="label"
              htmlFor="autoresearch-direction"
              size="1"
              weight="medium"
              className="mb-1 block"
            >
              Direction
            </Text>
            <Select.Root
              value={values.direction}
              onValueChange={(value) =>
                setField("direction", value as AutoresearchDirection)
              }
            >
              <Select.Trigger id="autoresearch-direction" className="w-full" />
              <Select.Content>
                <Select.Item value="maximize">Maximize</Select.Item>
                <Select.Item value="minimize">Minimize</Select.Item>
              </Select.Content>
            </Select.Root>
          </div>
          <div className="flex-1">
            <Text
              as="label"
              htmlFor="autoresearch-target"
              size="1"
              weight="medium"
              className="mb-1 block"
            >
              Target (optional)
            </Text>
            <TextField.Root
              id="autoresearch-target"
              value={values.targetValue}
              onChange={(event) => setField("targetValue", event.target.value)}
              placeholder="Stop early at…"
              inputMode="decimal"
            />
          </div>
          <div className="w-28">
            <Text
              as="label"
              htmlFor="autoresearch-iterations"
              size="1"
              weight="medium"
              className="mb-1 block"
            >
              Iterations
            </Text>
            <TextField.Root
              id="autoresearch-iterations"
              value={values.maxIterations}
              onChange={(event) =>
                setField("maxIterations", event.target.value)
              }
              inputMode="numeric"
            />
          </div>
        </Flex>

        {modelOptions.length > 0 && (
          <div className="flex flex-col gap-2">
            <StageRow
              legend="Implementation (ideate & build)"
              idPrefix="autoresearch-implement"
              model={values.implementModel}
              effort={values.implementEffort}
              modelOptions={modelOptions}
              effortOptions={effortOptions}
              onModelChange={(value) => setField("implementModel", value)}
              onEffortChange={(value) => setField("implementEffort", value)}
            />
            <StageRow
              legend="Experiment (measure)"
              idPrefix="autoresearch-measure"
              model={values.measureModel}
              effort={values.measureEffort}
              modelOptions={modelOptions}
              effortOptions={effortOptions}
              onModelChange={(value) => setField("measureModel", value)}
              onEffortChange={(value) => setField("measureEffort", value)}
            />
            <Text as="div" size="1" color="gray">
              Identical stages run each iteration as one turn. Different stages
              split every iteration: build on the first, then measure on the
              second. pick a cheap model or low effort for measuring.
            </Text>
          </div>
        )}

        {showInstructions && (
          <div>
            <Text
              as="label"
              htmlFor="autoresearch-instructions"
              size="1"
              weight="medium"
              className="mb-1 block"
            >
              Optimization brief
            </Text>
            <TextArea
              id="autoresearch-instructions"
              value={values.instructions}
              onChange={(event) => setField("instructions", event.target.value)}
              placeholder="What to optimize, how to measure it, and any constraints to respect."
              rows={4}
            />
          </div>
        )}

        {error && (
          <Text size="1" color="red">
            {error}
          </Text>
        )}
      </Flex>

      <Flex justify="end" gap="2" mt="4">
        <Dialog.Close>
          <Button variant="soft" color="gray" size="1">
            Cancel
          </Button>
        </Dialog.Close>
        <Button size="1" onClick={handleSubmit} disabled={!canSubmit}>
          {submitLabel}
        </Button>
      </Flex>
    </>
  );
}

function StageRow({
  legend,
  idPrefix,
  model,
  effort,
  modelOptions,
  effortOptions,
  onModelChange,
  onEffortChange,
}: {
  legend: string;
  idPrefix: string;
  model: string | null;
  effort: string | null;
  modelOptions: AutoresearchModelOption[];
  effortOptions: AutoresearchModelOption[];
  onModelChange: (value: string | null) => void;
  onEffortChange: (value: string | null) => void;
}) {
  return (
    <div>
      <Text as="div" size="1" weight="medium" className="mb-1">
        {legend}
      </Text>
      <Flex gap="2">
        <StageModelSelect
          id={`${idPrefix}-model`}
          ariaLabel={`${legend} model`}
          noneLabel="Session model"
          value={model}
          options={modelOptions}
          className="min-w-0 flex-1"
          onChange={onModelChange}
        />
        {effortOptions.length > 0 && (
          <StageModelSelect
            id={`${idPrefix}-effort`}
            ariaLabel={`${legend} effort`}
            noneLabel="Default effort"
            value={effort}
            options={effortOptions}
            className="w-32"
            onChange={onEffortChange}
          />
        )}
      </Flex>
    </div>
  );
}
