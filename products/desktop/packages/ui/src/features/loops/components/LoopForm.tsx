import {
  ArrowLeft,
  ArrowRight,
  CaretRight,
  Check,
} from "@phosphor-icons/react";
import { type LoopSchemas, LoopsApiError } from "@posthog/api-client/loops";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Button } from "@posthog/ui/primitives/Button";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToLoopDetail,
  navigateToLoops,
} from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { Box, Flex, Text, TextArea, TextField } from "@radix-ui/themes";
import {
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useAuthStateValue } from "../../auth/store";
import {
  useCreateLoop,
  useDeleteLoop,
  useUpdateLoop,
} from "../hooks/useLoopMutations";
import {
  useBundleLocalSkill,
  useReplaceLoopSkillBundles,
} from "../hooks/useLoopSkillBundles";
import { buildLoopSavedProps } from "../loopAnalytics";
import { summarizeTrigger } from "../loopDisplay";
import { useLoopDraftStore } from "../loopDraftStore";
import {
  emptyLoopFormValues,
  formValuesToLoopWrite,
  isAutoFixEnabled,
  isLoopFormValid,
  isTriggerDraftValid,
  type LoopContextTargetDraft,
  type LoopFormValues,
  loopToFormValues,
  normalizeLoopFormValues,
} from "../loopFormTypes";
import { formatLoopModel } from "../loopModels";
import { buildSkillInstructions, loopSkillBundles } from "../loopSkill";
import { LoopBehaviorFields } from "./LoopBehaviorFields";
import { LoopContextFields } from "./LoopContextFields";
import { Field } from "./LoopFormPrimitives";
import { LoopHeaderTitle } from "./LoopHeaderTitle";
import { LoopModelFields } from "./LoopModelFields";
import { LoopNotificationsFields } from "./LoopNotificationsFields";
import { LoopRepositoryPicker } from "./LoopRepositoryPicker";
import { LoopInstructionsFields } from "./LoopSkillFields";
import { LoopSpaceBreadcrumb } from "./LoopSpaceBreadcrumb";
import { LoopTriggerEditor } from "./LoopTriggerEditor";

const VISIBILITY_OPTIONS: {
  value: LoopSchemas.LoopVisibilityEnum;
  label: string;
}[] = [
  { value: "personal", label: "Personal (only you)" },
  { value: "team", label: "Team (everyone on the project)" },
];

const ADAPTER_LABELS: Record<LoopSchemas.LoopRuntimeAdapterEnum, string> = {
  claude: "Claude Code",
  codex: "Codex",
};

const STEPS = ["Prompt", "When", "Settings", "Review"] as const;

type LoopFormBaseline = {
  loopId: string;
  updatedAt: string;
  values: LoopFormValues;
  serialized: string;
};

function buildLoopFormBaseline(loop: LoopSchemas.Loop): LoopFormBaseline {
  const values = normalizeLoopFormValues(loopToFormValues(loop));
  return {
    loopId: loop.id,
    updatedAt: loop.updated_at,
    values,
    serialized: JSON.stringify(values),
  };
}

interface LoopFormProps {
  /** Present in edit mode; absent when creating a new loop. */
  loop?: LoopSchemas.Loop;
  variant?: "wizard" | "embedded";
  onCancel?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  onSaved?: (loop: LoopSchemas.Loop) => void;
}

type LoopFormSource = {
  loopId: string | null;
  updatedAt: string | null;
  values: LoopFormValues;
  serialized: string;
};

type LoopFormDraft = {
  baselineLoopId: string | null;
  baselineUpdatedAt: string | null;
  baselineSerialized: string;
  values: LoopFormValues;
};

type LoopFormViewProps = {
  canSubmit: boolean;
  handleCancel: () => void;
  handleSubmit: () => Promise<void>;
  hasRemoteUpdate: boolean;
  isEdit: boolean;
  isLastStep: boolean;
  isSubmitting: boolean;
  patch: (next: Partial<LoopFormValues>) => void;
  setShowAdvanced: Dispatch<SetStateAction<boolean>>;
  setStep: Dispatch<SetStateAction<number>>;
  showAdvanced: boolean;
  showContextField: boolean;
  step: number;
  stepComplete: boolean[];
  triggerEndpointPath: string | null;
  updateValues: (updater: (prev: LoopFormValues) => LoopFormValues) => void;
  values: LoopFormValues;
};

export function LoopForm({
  loop,
  variant = "wizard",
  onCancel,
  onDirtyChange,
  onSaved,
}: LoopFormProps) {
  const isEdit = !!loop;
  const isEmbedded = variant === "embedded";
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const [createInitialValues] = useState<LoopFormValues>(() => {
    if (loop) return normalizeLoopFormValues(emptyLoopFormValues());
    // One-shot prefill from the landing prompt or a template; merged over the
    // blank defaults. Read (not consumed) here, then cleared in the effect
    // below so the manual "New loop" button always opens a blank form.
    const prefill = useLoopDraftStore.getState().prefill;
    return normalizeLoopFormValues({
      ...emptyLoopFormValues(),
      ...(prefill ?? {}),
    });
  });
  const source = useMemo<LoopFormSource>(() => {
    const values = loop
      ? buildLoopFormBaseline(loop).values
      : createInitialValues;
    return {
      loopId: loop?.id ?? null,
      updatedAt: loop?.updated_at ?? null,
      values,
      serialized: JSON.stringify(values),
    };
  }, [loop, createInitialValues]);
  const [draft, setDraft] = useState<LoopFormDraft | null>(null);
  const [step, setStep] = useState(0);
  // Open when editing a loop that already pins a model, so the pinned value
  // is visible without hunting for it.
  const [showAdvanced, setShowAdvanced] = useState(
    () => !!(loop && (loop.model || loop.reasoning_effort)),
  );
  const draftIsDirty =
    !!draft && JSON.stringify(draft.values) !== draft.baselineSerialized;
  const useDraft =
    !!draft &&
    draft.baselineLoopId === source.loopId &&
    (draftIsDirty || draft.baselineSerialized !== source.serialized);
  const values = useDraft ? draft.values : source.values;
  const hasRemoteUpdate =
    !!loop &&
    draftIsDirty &&
    draft.baselineLoopId === source.loopId &&
    draft.baselineUpdatedAt !== loop.updated_at;

  useEffect(() => {
    if (!loop) useLoopDraftStore.getState().setPrefill(null);
  }, [loop]);

  // Contexts are a channels surface; hide the attachment UI when channels are
  // off, unless this loop is already attached so the link stays visible and
  // detachable.
  const bluebirdEnabled = useBluebirdFlag();
  const channelsEnabled =
    useSidebarStore((s) => s.channelsEnabled) && bluebirdEnabled;
  const showContextField = channelsEnabled || !!values.contextTarget;

  // Per-step gate for the Next button. The final Create button is gated on the
  // whole form being valid, so jumping between steps can't submit a bad loop.
  const stepComplete = [
    !!values.name.trim() &&
      (values.skill !== null || !!values.instructions.trim()),
    values.triggers.every(isTriggerDraftValid),
    true,
    isLoopFormValid(values),
  ];
  const isLastStep = step === STEPS.length - 1;

  // Building a loop for a space keeps a way back to it; without one the header
  // still names the scene, it just has no parent to offer.
  const spacesLayout = useChannelsLayout();
  const contextTarget = values.contextTarget;
  const headerLeaf = isEdit ? loop.name : "New loop";
  useSetHeaderContent(
    useMemo(
      () =>
        spacesLayout && contextTarget ? (
          <LoopSpaceBreadcrumb
            folderId={contextTarget.folderId}
            spaceName={contextTarget.name}
            leafLabel={headerLeaf}
          />
        ) : (
          <LoopHeaderTitle label={headerLeaf} />
        ),
      [spacesLayout, contextTarget, headerLeaf],
    ),
  );

  const triggerEndpointPath =
    isEdit && projectId != null
      ? `/api/projects/${projectId}/loops/${loop.id}/trigger/`
      : null;

  const patch = (next: Partial<LoopFormValues>) =>
    updateValues((prev) => ({ ...prev, ...next }));

  const updateValues = (updater: (prev: LoopFormValues) => LoopFormValues) => {
    const baseline =
      draft && useDraft
        ? draft
        : {
            baselineUpdatedAt: source.updatedAt,
            baselineLoopId: source.loopId,
            baselineSerialized: source.serialized,
            values: source.values,
          };
    const nextValues = updater(values);
    setDraft({ ...baseline, values: nextValues });
    onDirtyChange?.(JSON.stringify(nextValues) !== baseline.baselineSerialized);
  };

  const markClean = (saved: LoopSchemas.Loop) => {
    const nextValues = normalizeLoopFormValues(loopToFormValues(saved));
    setDraft({
      baselineLoopId: saved.id,
      baselineUpdatedAt: saved.updated_at,
      baselineSerialized: JSON.stringify(nextValues),
      values: nextValues,
    });
    onDirtyChange?.(false);
  };

  const { canSubmit, handleSubmit, isSubmitting } = useLoopFormSubmit({
    hasRemoteUpdate,
    loop,
    markClean,
    onSaved,
    values,
  });

  const handleCancel = () => {
    if (onCancel) {
      onCancel();
      return;
    }
    if (isEdit) {
      navigateToLoopDetail(loop.id);
    } else {
      navigateToLoops();
    }
  };

  const viewProps: LoopFormViewProps = {
    canSubmit,
    handleCancel,
    handleSubmit,
    hasRemoteUpdate,
    isEdit,
    isLastStep,
    isSubmitting,
    patch,
    setShowAdvanced,
    setStep,
    showAdvanced,
    showContextField,
    step,
    stepComplete,
    triggerEndpointPath,
    updateValues,
    values,
  };

  return isEmbedded
    ? renderEmbeddedLoopForm(viewProps)
    : renderWizardLoopForm(viewProps);
}

function renderEmbeddedLoopForm({
  canSubmit,
  handleCancel,
  handleSubmit,
  hasRemoteUpdate,
  isSubmitting,
  patch,
  showContextField,
  triggerEndpointPath,
  updateValues,
  values,
}: LoopFormViewProps) {
  return (
    <Flex
      direction="column"
      gap="4"
      className="rounded-(--radius-2) border border-border bg-(--gray-1) p-4"
    >
      {renderStep({
        title: "Prompt",
        description:
          "Name the loop and describe what PostHog should do each time it runs.",
        children: (
          <>
            <Field label="Name" required>
              <TextField.Root
                size="2"
                value={values.name}
                placeholder="Daily standup summary"
                disabled={isSubmitting}
                onChange={(e) => patch({ name: e.target.value })}
              />
            </Field>
            <Field label="Description">
              <TextArea
                value={values.description}
                placeholder="A short summary shown on the Loops list"
                disabled={isSubmitting}
                className="min-h-[72px] text-[13px] leading-relaxed"
                onChange={(e) => patch({ description: e.target.value })}
              />
            </Field>
            <LoopInstructionsFields
              values={values}
              disabled={isSubmitting}
              onPatch={patch}
            />
          </>
        ),
      })}

      {renderDivider()}

      {renderStep({
        title: "When",
        description: "Add automatic triggers, or leave this manual-only.",
        children: (
          <LoopTriggerEditor
            triggers={values.triggers}
            triggerEndpointPath={triggerEndpointPath}
            disabled={isSubmitting}
            onChange={(triggers) => patch({ triggers })}
          />
        ),
      })}

      {renderDivider()}

      {renderStep({
        title: "Settings",
        description:
          "Choose who can see it, where it works, and when to notify you.",
        children: renderEmbeddedSettingsFields({
          isSubmitting,
          patch,
          showContextField,
          updateValues,
          values,
        }),
      })}

      {renderDivider()}

      {renderStep({
        title: "Advanced",
        description: "Model, reasoning, and pull requests.",
        children: renderAdvancedFields({ isSubmitting, patch, values }),
      })}

      {renderRemoteUpdateNotice(hasRemoteUpdate)}

      <Flex
        align="center"
        justify="end"
        gap="2"
        className="sticky bottom-0 z-10 border-border border-t bg-(--gray-1) py-4"
      >
        <Button
          variant="soft"
          color="gray"
          size="2"
          disabled={isSubmitting}
          onClick={handleCancel}
        >
          Cancel
        </Button>
        <Button
          variant="solid"
          size="2"
          loading={isSubmitting}
          disabled={!canSubmit}
          onClick={() => void handleSubmit()}
        >
          Save changes
        </Button>
      </Flex>
    </Flex>
  );
}

function renderWizardLoopForm(props: LoopFormViewProps) {
  const {
    canSubmit,
    handleCancel,
    handleSubmit,
    isEdit,
    isLastStep,
    isSubmitting,
    setStep,
    step,
    stepComplete,
  } = props;

  return (
    <Box className="flex h-full items-center justify-center p-6">
      <Flex
        direction="column"
        className="max-h-full w-full max-w-[640px] overflow-hidden rounded-(--radius-3) border border-border bg-(--color-panel-solid) shadow-xl"
      >
        <Box className="border-border border-b px-6 pt-5 pb-4">
          {renderStepper({
            complete: stepComplete,
            current: step,
            onSelect: setStep,
          })}
        </Box>

        <Box className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
          {step === 0 ? renderPromptStep(props) : null}
          {step === 1 ? renderWhenStep(props) : null}
          {step === 2 ? renderSettingsStep(props) : null}
          {step === 3 ? renderReviewStep(props) : null}
        </Box>

        <Flex
          align="center"
          justify="between"
          gap="3"
          className="border-border border-t px-5 py-3"
        >
          <Button
            variant="soft"
            color="gray"
            size="2"
            disabled={isSubmitting}
            onClick={handleCancel}
          >
            Cancel
          </Button>
          <Flex gap="2" className="shrink-0">
            {step > 0 ? (
              <Button
                variant="outline"
                color="gray"
                size="2"
                disabled={isSubmitting}
                onClick={() => setStep((s) => s - 1)}
              >
                <ArrowLeft size={13} />
                Back
              </Button>
            ) : null}
            {isLastStep ? (
              <Button
                variant="solid"
                size="2"
                loading={isSubmitting}
                disabled={!canSubmit}
                onClick={() => void handleSubmit()}
              >
                {isEdit ? "Save changes" : "Create loop"}
              </Button>
            ) : (
              <Button
                variant="solid"
                size="2"
                disabled={!stepComplete[step] || isSubmitting}
                onClick={() => setStep((s) => s + 1)}
              >
                Next
                <ArrowRight size={13} />
              </Button>
            )}
          </Flex>
        </Flex>
      </Flex>
    </Box>
  );
}

function renderPromptStep({ isSubmitting, patch, values }: LoopFormViewProps) {
  return renderStep({
    title: "What should this loop do?",
    description:
      "Name the loop and describe what PostHog should do each time it runs.",
    children: (
      <>
        <Field label="Name" required>
          <TextField.Root
            size="2"
            value={values.name}
            placeholder="Daily standup summary"
            disabled={isSubmitting}
            autoFocus
            onChange={(e) => patch({ name: e.target.value })}
          />
        </Field>
        <Field label="Description">
          <TextField.Root
            size="2"
            value={values.description}
            placeholder="A short summary shown on the Loops list"
            disabled={isSubmitting}
            onChange={(e) => patch({ description: e.target.value })}
          />
        </Field>
        <LoopInstructionsFields
          values={values}
          disabled={isSubmitting}
          onPatch={patch}
        />
      </>
    ),
  });
}

function renderWhenStep({
  isSubmitting,
  patch,
  triggerEndpointPath,
  values,
}: LoopFormViewProps) {
  return renderStep({
    title: "When should it run?",
    description: "Add one or more triggers. Any trigger can start the loop.",
    children: (
      <LoopTriggerEditor
        triggers={values.triggers}
        triggerEndpointPath={triggerEndpointPath}
        disabled={isSubmitting}
        onChange={(triggers) => patch({ triggers })}
      />
    ),
  });
}

function renderSettingsStep(props: LoopFormViewProps) {
  return renderStep({
    title: "Settings",
    description:
      "Choose who can see it, where it works, and when to notify you.",
    children: (
      <>
        {renderSettingsSection({
          title: "Access",
          children: renderVisibilityField(props, {
            className: "max-w-[340px]",
            channelHint:
              "Loops attached to a channel post runs to its shared feed, so they're visible to everyone on the project.",
          }),
        })}

        {props.showContextField
          ? renderSettingsSection({
              title: "Channel context",
              children: renderContextField(props, {
                hint: "Attach this loop to a sidebar channel. Runs show in the channel feed. The loop can also update context.md or a canvas.",
              }),
            })
          : null}

        {renderSettingsSection({
          title: "Repository",
          children: renderRepositoryField(props, {
            multipleHint: (count) =>
              `${count - 1} more ${
                count === 2 ? "repository stays" : "repositories stay"
              } attached to this loop.`,
            singleHint:
              "Optional. Choose a repository if this loop should read code or open PRs. Leave empty for report-only loops.",
          }),
        })}

        {renderSettingsSection({
          title: "Notifications",
          description:
            "Full run output is always saved on the loop page. Notifications send a short summary and link.",
          children: (
            <LoopNotificationsFields
              notifications={props.values.notifications}
              disabled={props.isSubmitting}
              onChange={(notifications) => props.patch({ notifications })}
            />
          ),
        })}

        {renderAdvancedDisclosure(props)}
      </>
    ),
  });
}

function renderEmbeddedSettingsFields(props: {
  isSubmitting: boolean;
  patch: (next: Partial<LoopFormValues>) => void;
  showContextField: boolean;
  updateValues: (updater: (prev: LoopFormValues) => LoopFormValues) => void;
  values: LoopFormValues;
}) {
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        {renderVisibilityField(props, {
          channelHint: "Channel loops are team-visible.",
        })}
        {renderRepositoryField(props, {
          multipleHint: (count) => `${count - 1} more attached.`,
          singleHint:
            "Optional. Choose a repository if this loop should read code or open PRs.",
        })}
      </div>

      {props.showContextField
        ? renderContextField(props, {
            hint: "Attach runs to a sidebar channel.",
          })
        : null}

      <Field label="Notifications">
        <LoopNotificationsFields
          notifications={props.values.notifications}
          disabled={props.isSubmitting}
          onChange={(notifications) => props.patch({ notifications })}
        />
      </Field>
    </>
  );
}

function renderVisibilityField(
  {
    isSubmitting,
    patch,
    values,
  }: Pick<LoopFormViewProps, "isSubmitting" | "patch" | "values">,
  options: { channelHint: string; className?: string },
) {
  return (
    <Field
      label="Visibility"
      className={options.className}
      hint={values.contextTarget ? options.channelHint : undefined}
    >
      <SettingsOptionSelect
        value={values.visibility}
        options={VISIBILITY_OPTIONS}
        disabled={isSubmitting || !!values.contextTarget}
        size="lg"
        ariaLabel="Visibility"
        onValueChange={(value) =>
          patch({
            visibility: value as LoopSchemas.LoopVisibilityEnum,
          })
        }
      />
    </Field>
  );
}

function renderRepositoryField(
  {
    isSubmitting,
    updateValues,
    values,
  }: Pick<LoopFormViewProps, "isSubmitting" | "updateValues" | "values">,
  options: {
    multipleHint: (count: number) => string;
    singleHint: string;
  },
) {
  return (
    <Field
      label="Base repository"
      hint={
        values.repositories.length > 1
          ? options.multipleHint(values.repositories.length)
          : options.singleHint
      }
    >
      <LoopRepositoryPicker
        value={values.repositories[0] ?? null}
        disabled={isSubmitting}
        onChange={(repository) =>
          updateValues((prev) => ({
            ...prev,
            repositories: repository
              ? [repository, ...prev.repositories.slice(1)]
              : prev.repositories.slice(1),
          }))
        }
      />
    </Field>
  );
}

function renderContextField(
  {
    isSubmitting,
    patch,
    values,
  }: Pick<LoopFormViewProps, "isSubmitting" | "patch" | "values">,
  options: { hint: string },
) {
  return (
    <Field label="Context" hint={options.hint}>
      <LoopContextFields
        value={values.contextTarget}
        disabled={isSubmitting}
        onChange={(contextTarget) =>
          patch(
            contextTarget
              ? { contextTarget, visibility: "team" }
              : { contextTarget },
          )
        }
      />
    </Field>
  );
}

function renderAdvancedDisclosure({
  isSubmitting,
  patch,
  setShowAdvanced,
  showAdvanced,
  values,
}: LoopFormViewProps) {
  return renderSettingsSection({
    children: (
      <>
        <button
          type="button"
          onClick={() => setShowAdvanced((open) => !open)}
          className="flex items-center gap-1.5 text-left"
        >
          <CaretRight
            size={12}
            className={`text-gray-10 transition-transform ${
              showAdvanced ? "rotate-90" : ""
            }`}
          />
          <Text className="font-medium text-[12.5px] text-gray-11">
            Advanced
          </Text>
          <Text className="text-[11.5px] text-gray-9">
            Model, reasoning, and pull requests
          </Text>
        </button>
        {showAdvanced
          ? renderAdvancedFields({ isSubmitting, patch, values })
          : null}
      </>
    ),
  });
}

function renderAdvancedFields({
  isSubmitting,
  patch,
  values,
}: Pick<LoopFormViewProps, "isSubmitting" | "patch" | "values">) {
  return (
    <Flex direction="column" gap="4">
      <Field label="Behavior">
        <LoopBehaviorFields
          behaviors={values.behaviors}
          disabled={isSubmitting}
          onChange={(behaviors) => patch({ behaviors })}
        />
      </Field>
      <LoopModelFields
        adapter={values.runtimeAdapter}
        model={values.model}
        reasoningEffort={values.reasoningEffort}
        disabled={isSubmitting}
        onAdapterChange={(runtimeAdapter) => patch({ runtimeAdapter })}
        onModelChange={(model) => patch({ model })}
        onReasoningEffortChange={(reasoningEffort) =>
          patch({ reasoningEffort })
        }
      />
    </Flex>
  );
}

function renderReviewStep({
  setStep,
  showContextField,
  values,
}: LoopFormViewProps) {
  return renderStep({
    title: "Review",
    description: "Check the loop before creating it.",
    children: renderReviewList({
      values,
      showContext: showContextField,
      onEdit: setStep,
    }),
  });
}

function renderRemoteUpdateNotice(hasRemoteUpdate: boolean) {
  return hasRemoteUpdate ? (
    <Flex
      direction="column"
      gap="1"
      className="rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-3 py-2"
    >
      <Text className="font-medium text-(--amber-12) text-[12.5px]">
        This loop changed elsewhere
      </Text>
      <Text className="text-(--amber-11) text-[12px] leading-snug">
        Cancel and reopen editing before saving, so you don't overwrite newer
        settings.
      </Text>
    </Flex>
  ) : null;
}

function renderStepper({
  current,
  complete,
  onSelect,
}: {
  current: number;
  complete: boolean[];
  onSelect: (step: number) => void;
}) {
  return (
    <Flex align="center" gap="0">
      {STEPS.map((label, index) => {
        const isCurrent = index === current;
        const isDone = index < current && complete[index];
        const canSelect =
          index <= current || complete.slice(current, index).every(Boolean);
        return (
          <Flex
            key={label}
            align="center"
            className="min-w-0 flex-1 last:flex-none"
          >
            <button
              type="button"
              disabled={!canSelect}
              onClick={() => {
                if (canSelect) onSelect(index);
              }}
              className="flex min-w-0 cursor-pointer items-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Flex
                align="center"
                justify="center"
                className={`size-5 shrink-0 rounded-full border font-medium text-[11px] ${
                  isCurrent
                    ? "border-(--accent-9) bg-(--accent-9) text-(--accent-contrast)"
                    : isDone
                      ? "border-(--accent-7) bg-(--accent-3) text-(--accent-11)"
                      : "border-(--gray-7) text-gray-11"
                }`}
              >
                {isDone ? <Check size={12} weight="bold" /> : index + 1}
              </Flex>
              <Text
                className={`truncate text-[12.5px] ${
                  isCurrent ? "font-medium text-gray-12" : "text-gray-11"
                }`}
              >
                {label}
              </Text>
            </button>
            {index < STEPS.length - 1 ? (
              <Box className="mx-2 h-px min-w-4 flex-1 bg-(--gray-5)" />
            ) : null}
          </Flex>
        );
      })}
    </Flex>
  );
}

function useLoopFormSubmit({
  hasRemoteUpdate,
  loop,
  markClean,
  onSaved,
  values,
}: {
  hasRemoteUpdate: boolean;
  loop?: LoopSchemas.Loop;
  markClean: (loop: LoopSchemas.Loop) => void;
  onSaved?: (loop: LoopSchemas.Loop) => void;
  values: LoopFormValues;
}) {
  const isEdit = !!loop;
  const createLoop = useCreateLoop();
  const updateLoop = useUpdateLoop(loop?.id ?? "");
  const deleteLoop = useDeleteLoop();
  const bundleSkill = useBundleLocalSkill();
  const replaceSkillBundles = useReplaceLoopSkillBundles();
  const isSubmitting =
    (isEdit ? updateLoop.isPending : createLoop.isPending) ||
    bundleSkill.isPending ||
    replaceSkillBundles.isPending ||
    deleteLoop.isPending;
  const canSubmit =
    isLoopFormValid(values) && !isSubmitting && !hasRemoteUpdate;

  const handleSubmit = async () => {
    if (hasRemoteUpdate) {
      toast.error("Loop changed elsewhere", {
        description: "Cancel and reopen editing before saving changes.",
      });
      return;
    }
    if (!canSubmit) return;
    const body = formValuesToLoopWrite(values);

    // Bundling runs before anything is persisted: a missing or broken local
    // skill fails here with no partial state, instead of leaving a saved loop
    // whose `/skill-name` instructions have no matching bundle.
    let uploads: LoopSchemas.LoopSkillBundleUpload[] | null = null;
    if (values.skill?.kind === "local") {
      try {
        uploads = await bundleSkill.mutateAsync(values.skill);
      } catch (error) {
        toast.error("Failed to bundle the skill", {
          description: error instanceof Error ? error.message : undefined,
        });
        return;
      }
    }

    try {
      const saved = isEdit
        ? await updateLoop.mutateAsync(body)
        : await createLoop.mutateAsync(body);
      markClean(saved);
      track(
        isEdit ? ANALYTICS_EVENTS.LOOP_UPDATED : ANALYTICS_EVENTS.LOOP_CREATED,
        buildLoopSavedProps(saved),
      );
      const needsDetach =
        values.skill === null && loopSkillBundles(saved).length > 0;
      if (uploads || needsDetach) {
        const uploaded = await replaceSavedLoopBundles({
          deleteLoop: deleteLoop.mutateAsync,
          isEdit,
          replaceSkillBundles: replaceSkillBundles.mutateAsync,
          saved,
          uploads,
        });
        if (!uploaded) return;
      }
      if (onSaved) {
        onSaved(saved);
      } else {
        navigateToLoopDetail(saved.id);
      }
    } catch (error) {
      const safetyLimit =
        error instanceof LoopsApiError ? error.safetyLimit : null;
      if (safetyLimit) {
        // A safety/abuse ceiling, not a normal failure: tell the user plainly so they can
        // course-correct (delete a loop, remove triggers) or contact support for a raise.
        toast.error("Safety limit reached", {
          description: safetyLimit.detail,
        });
        return;
      }
      toast.error(isEdit ? "Failed to save loop" : "Failed to create loop", {
        description:
          error instanceof LoopsApiError
            ? (error.detail ?? error.message)
            : error instanceof Error
              ? error.message
              : undefined,
      });
    }
  };

  return { canSubmit, handleSubmit, isSubmitting };
}

async function replaceSavedLoopBundles({
  deleteLoop,
  isEdit,
  replaceSkillBundles,
  saved,
  uploads,
}: {
  deleteLoop: (loopId: string) => Promise<unknown>;
  isEdit: boolean;
  replaceSkillBundles: (input: {
    loopId: string;
    uploads: LoopSchemas.LoopSkillBundleUpload[];
  }) => Promise<unknown>;
  saved: LoopSchemas.Loop;
  uploads: LoopSchemas.LoopSkillBundleUpload[] | null;
}) {
  try {
    await replaceSkillBundles({
      loopId: saved.id,
      uploads: uploads ?? [],
    });
    return true;
  } catch (error) {
    const description = error instanceof Error ? error.message : undefined;
    if (!isEdit) {
      try {
        await deleteLoop(saved.id);
        toast.error("Failed to create loop", { description });
      } catch {
        toast.error("Loop created, but attaching its skill failed", {
          description: [
            description,
            `Delete "${saved.name}" or re-save it from Edit.`,
          ]
            .filter(Boolean)
            .join(" "),
        });
      }
      return false;
    }
    toast.error("Loop saved, but updating its skill failed", {
      description: [description, "Save again to retry."]
        .filter(Boolean)
        .join(" "),
    });
    return false;
  }
}

function renderStep({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <Flex direction="column" gap="4">
      <Flex direction="column" gap="1">
        <Text className="font-medium text-[15px] text-gray-12">{title}</Text>
        <Text className="text-[12.5px] text-gray-10 leading-snug">
          {description}
        </Text>
      </Flex>
      {children}
    </Flex>
  );
}

function renderDivider() {
  return <Box className="h-px bg-(--gray-4)" />;
}

function renderSettingsSection({
  title,
  description,
  children,
}: {
  title?: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Flex direction="column" gap="3">
      {title || description ? (
        <Flex direction="column" gap="1">
          {title ? (
            <Text className="font-medium text-[13px] text-gray-12">
              {title}
            </Text>
          ) : null}
          {description ? (
            <Text className="text-[12px] text-gray-10 leading-snug">
              {description}
            </Text>
          ) : null}
        </Flex>
      ) : null}
      {children}
      {renderDivider()}
    </Flex>
  );
}

function renderReviewList({
  values,
  showContext,
  onEdit,
}: {
  values: LoopFormValues;
  showContext: boolean;
  onEdit: (step: number) => void;
}) {
  const reasoning = values.reasoningEffort ?? "auto";
  const channels = (["push", "email", "slack"] as const).filter(
    (channel) => values.notifications[channel]?.enabled,
  );

  return (
    <Flex
      direction="column"
      gap="3"
      className="rounded-(--radius-3) border border-border p-3"
    >
      {renderReviewSection({
        title: "Prompt",
        onEdit: () => onEdit(0),
        children: (
          <>
            {renderReviewRow({
              label: "Name",
              value: values.name || "Not set",
            })}
            {renderReviewRow({
              label: "Instructions",
              value: values.skill
                ? buildSkillInstructions(values.skill.name, values.skillContext)
                : values.instructions.trim() || "No instructions",
              multiline: true,
            })}
          </>
        ),
      })}

      {renderReviewSection({
        title: "Schedule",
        onEdit: () => onEdit(1),
        children: renderReviewRow({
          label: "Triggers",
          value:
            values.triggers.length === 0
              ? "Manual only"
              : values.triggers.map(summarizeTrigger).join(", "),
        }),
      })}

      {renderReviewSection({
        title: "Settings",
        onEdit: () => onEdit(2),
        children: (
          <>
            {renderReviewRow({
              label: "Visibility",
              value: values.visibility === "team" ? "Team" : "Personal",
            })}
            {showContext
              ? renderReviewRow({
                  label: "Context",
                  value: describeContext(values.contextTarget),
                })
              : null}
            {renderReviewRow({
              label: "Repository",
              value:
                values.repositories.length > 0
                  ? values.repositories.map((repo) => repo.full_name).join(", ")
                  : "None, report-only",
            })}
            {renderReviewRow({
              label: "Notifications",
              value: channels.length === 0 ? "None" : channels.join(", "),
            })}
            {renderReviewRow({
              label: "Auto-fix PRs",
              value: isAutoFixEnabled(values.behaviors) ? "On" : "Off",
            })}
            {renderReviewRow({
              label: "Model",
              value: `${ADAPTER_LABELS[values.runtimeAdapter]} · ${formatLoopModel(
                values.runtimeAdapter,
                values.model,
              )} · ${reasoning} reasoning`,
            })}
          </>
        ),
      })}
    </Flex>
  );
}

function renderReviewSection({
  title,
  onEdit,
  children,
}: {
  title: string;
  onEdit: () => void;
  children: ReactNode;
}) {
  return (
    <Flex direction="column" gap="2">
      <Flex align="center" justify="between" gap="2">
        <Text className="font-medium text-[13px] text-gray-12">{title}</Text>
        <button
          type="button"
          className="text-[12px] text-gray-10 hover:text-gray-12"
          onClick={onEdit}
        >
          Edit
        </button>
      </Flex>
      <Flex
        direction="column"
        className="divide-y divide-(--gray-4) rounded-(--radius-2) border border-border"
      >
        {children}
      </Flex>
    </Flex>
  );
}

function renderReviewRow({
  label,
  value,
  multiline,
}: {
  label: string;
  value: string;
  multiline?: boolean;
}) {
  return (
    <Flex gap="4" className="px-3 py-2.5">
      <Text className="w-28 shrink-0 text-[12px] text-gray-10">{label}</Text>
      <Text
        className={`min-w-0 flex-1 text-[12.5px] text-gray-12 ${
          multiline ? "whitespace-pre-wrap" : "truncate"
        }`}
      >
        {value}
      </Text>
    </Flex>
  );
}

function describeContext(target: LoopContextTargetDraft | null): string {
  if (!target) return "Not attached to a channel";
  const outputs: string[] = [];
  if (target.outputs.post_to_feed) outputs.push("feed");
  if (target.outputs.update_context) outputs.push("context.md");
  if (target.outputs.canvas_id) outputs.push("canvas");
  return outputs.length > 0
    ? `#${target.name} (${outputs.join(", ")})`
    : `#${target.name}`;
}
