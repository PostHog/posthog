import {
  ArrowLeft,
  ArrowRight,
  CaretRight,
  Check,
} from "@phosphor-icons/react";
import { requestErrorStatus } from "@posthog/api-client/fetcher";
import { hogFlowRequestDetail } from "@posthog/api-client/hogFlowLoops";
import { type LoopSchemas, LoopsApiError } from "@posthog/api-client/loops";
import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { useLoopsHogFlowsEnabled } from "@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { useSandboxEnvironments } from "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments";
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
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useAuthStateValue } from "../../auth/store";
import { useLoopHogFlow } from "../hooks/useLoop";
import {
  useCreateLoop,
  useCreateLoopHogFlow,
  useDeleteLoop,
  useUpdateLoop,
  useUpdateLoopHogFlow,
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
  isTriggerListValid,
  LOOPS_API_RULES,
  type LoopContextTargetDraft,
  type LoopFormValues,
  loopToFormValues,
  normalizeLoopFormValues,
  WORKFLOW_RULES,
} from "../loopFormTypes";
import {
  hogFlowTeamSkills,
  isLoopShapedHogFlow,
  UnsupportedLoopShapeError,
} from "../loopHogFlowMapping";
import {
  LoopForeignWorkflowError,
  LoopScheduleSaveError,
} from "../loopHogFlowWrites";
import { formatLoopModel } from "../loopModels";
import { buildSkillInstructions, loopSkillBundles } from "../loopSkill";
import { WORKFLOW_TRIGGER_LIMITS } from "../loopTriggerLimits";
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
import { LoopWorkflowPromptFields } from "./LoopWorkflowPromptFields";

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

const STEPS = ["Prompt", "When", "Options", "Review"] as const;

type LoopFormBaseline = {
  loopId: string;
  updatedAt: string;
  values: LoopFormValues;
  serialized: string;
};

function buildLoopFormBaseline(
  loop: LoopSchemas.Loop,
  teamSkills: string[],
): LoopFormBaseline {
  const values = normalizeLoopFormValues({
    ...loopToFormValues(loop),
    teamSkills,
  });
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
  const workflowBacked = useLoopsHogFlowsEnabled();
  // The loop prop is a projection of this same cached workflow, so it is
  // already loaded whenever `loop` is; the raw flow carries the team skills
  // and the schedule row the save needs to reconcile.
  const { data: hogFlow } = useLoopHogFlow(
    workflowBacked ? loop?.id : undefined,
  );
  const teamSkills = useMemo(
    () => (hogFlow ? hogFlowTeamSkills(hogFlow) : []),
    [hogFlow],
  );
  const rules = workflowBacked ? WORKFLOW_RULES : LOOPS_API_RULES;
  // One-shot prefill from the landing prompt, a template, or a space; merged
  // over the blank defaults. Read (not consumed) here, then cleared in the
  // effect below so the manual "New loop" button always opens a blank form.
  const [prefill] = useState(() =>
    loop ? null : useLoopDraftStore.getState().prefill,
  );
  // A workflow has nowhere to keep a space attachment, so a loop started from
  // a space opens detached and the form says so instead of dropping it quietly.
  const detachedSpace = workflowBacked
    ? (prefill?.contextTarget ?? null)
    : null;
  const [values, setValues] = useState<LoopFormValues>(() => {
    if (loop) {
      return normalizeLoopFormValues({
        ...loopToFormValues(loop),
        teamSkills,
      });
    }
    return normalizeLoopFormValues({
      ...emptyLoopFormValues(),
      ...(prefill ?? {}),
      ...(workflowBacked ? { contextTarget: null } : {}),
    });
  });
  const [step, setStep] = useState(0);
  const [baseline, setBaseline] = useState<LoopFormBaseline | null>(() =>
    loop ? buildLoopFormBaseline(loop, teamSkills) : null,
  );
  const [hasRemoteUpdate, setHasRemoteUpdate] = useState(false);
  // `updated_at` of a write this form made. When the loop with that stamp
  // arrives, the baseline moves onto it without treating it as someone
  // else's change, so a partial save (graph stuck, schedule did not) can be
  // saved again.
  const ownWriteUpdatedAtRef = useRef<string | null>(null);
  // Open when editing a loop that already pins a model, so the pinned value
  // is visible without hunting for it.
  const [showAdvanced, setShowAdvanced] = useState(
    () => !!(loop && (loop.model || loop.reasoning_effort)),
  );
  const isDirty = !!baseline && JSON.stringify(values) !== baseline.serialized;

  useEffect(() => {
    if (!loop) useLoopDraftStore.getState().setPrefill(null);
  }, [loop]);

  useEffect(() => {
    if (!loop) return;

    const nextBaseline = buildLoopFormBaseline(loop, teamSkills);
    if (!baseline || baseline.loopId !== loop.id) {
      setBaseline(nextBaseline);
      setValues(nextBaseline.values);
      setHasRemoteUpdate(false);
      return;
    }

    // A schedule row edit moves only the row's own `updated_at`, so the
    // cadence is compared through the serialized values as well.
    if (
      nextBaseline.updatedAt === baseline.updatedAt &&
      nextBaseline.serialized === baseline.serialized
    ) {
      return;
    }

    if (nextBaseline.updatedAt === ownWriteUpdatedAtRef.current) {
      ownWriteUpdatedAtRef.current = null;
      setBaseline(nextBaseline);
      return;
    }

    if (isDirty) {
      setHasRemoteUpdate(true);
      return;
    }

    setBaseline(nextBaseline);
    setValues(nextBaseline.values);
    setHasRemoteUpdate(false);
  }, [loop, teamSkills, baseline, isDirty]);

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  // Contexts are a channels surface; hide the attachment UI when channels are
  // off, unless this loop is already attached so the link stays visible and
  // detachable.
  const bluebirdEnabled = useBluebirdFlag();
  const channelsEnabled =
    useSidebarStore((s) => s.channelsEnabled) && bluebirdEnabled;
  const showContextField =
    !workflowBacked && (channelsEnabled || !!values.contextTarget);
  const { environments, isLoading: environmentsLoading } =
    useSandboxEnvironments();
  const sandboxEnvironmentOptions = useMemo(() => {
    const options = [
      { value: "", label: "Default environment" },
      ...environments.map((environment) => ({
        value: environment.id,
        label: environment.name,
      })),
    ];
    if (
      values.sandboxEnvironmentId &&
      !environments.some(
        (environment) => environment.id === values.sandboxEnvironmentId,
      )
    ) {
      options.push({
        value: values.sandboxEnvironmentId,
        label: "Unavailable environment",
      });
    }
    return options;
  }, [environments, values.sandboxEnvironmentId]);

  const createLoop = useCreateLoop();
  const updateLoop = useUpdateLoop(loop?.id ?? "");
  const createHogFlowLoop = useCreateLoopHogFlow();
  const updateHogFlowLoop = useUpdateLoopHogFlow(loop?.id ?? "");
  const deleteLoop = useDeleteLoop();
  const bundleSkill = useBundleLocalSkill();
  const replaceSkillBundles = useReplaceLoopSkillBundles();
  const isSubmitting =
    (isEdit ? updateLoop.isPending : createLoop.isPending) ||
    createHogFlowLoop.isPending ||
    updateHogFlowLoop.isPending ||
    bundleSkill.isPending ||
    replaceSkillBundles.isPending ||
    deleteLoop.isPending;
  const canSubmit =
    isLoopFormValid(values, rules) && !isSubmitting && !hasRemoteUpdate;

  // Per-step gate for the Next button. The final Create button is gated on the
  // whole form being valid, so jumping between steps can't submit a bad loop.
  const stepComplete = [
    !!values.name.trim() &&
      (values.skill !== null || !!values.instructions.trim()),
    isTriggerListValid(values.triggers, rules),
    true,
    isLoopFormValid(values, rules),
  ];
  const isLastStep = step === STEPS.length - 1;

  // Building a loop for a space keeps a way back to it, attached or not;
  // without one the header still names the scene, it just has no parent to
  // offer.
  const spacesLayout = useChannelsLayout();
  const contextTarget = values.contextTarget ?? detachedSpace;
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
    setValues((prev) => ({ ...prev, ...next }));

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

  const reportForeignWorkflow = () => {
    toast.error("This loop was changed in the workflow editor", {
      description:
        "Open it in PostHog to change it. Saving here would replace those changes.",
    });
  };

  const submitWorkflowLoop = async () => {
    if (isEdit && !hogFlow) {
      toast.error("Loop is still loading", {
        description: "Wait a moment and save again.",
      });
      return;
    }
    // The detail page checks the shape when it renders; a reshaped flow can
    // still arrive while the form is open, or the form can open by URL.
    if (isEdit && hogFlow && !isLoopShapedHogFlow(hogFlow)) {
      reportForeignWorkflow();
      return;
    }
    try {
      const saved =
        isEdit && hogFlow
          ? await updateHogFlowLoop.mutateAsync({ values, existing: hogFlow })
          : await createHogFlowLoop.mutateAsync({ values, enabled: true });
      ownWriteUpdatedAtRef.current = saved.updated_at;
      track(
        isEdit ? ANALYTICS_EVENTS.LOOP_UPDATED : ANALYTICS_EVENTS.LOOP_CREATED,
        buildLoopSavedProps(saved),
      );
      if (onSaved) {
        onSaved(saved);
      } else {
        navigateToLoopDetail(saved.id);
      }
    } catch (error) {
      if (error instanceof LoopScheduleSaveError) {
        // Keep the form open with its state intact: saving again retries the
        // schedule write against the graph that already stuck.
        ownWriteUpdatedAtRef.current = error.flow.updated_at;
        toast.error("Loop saved, but its schedule didn't update", {
          description: [
            hogFlowRequestDetail(error.cause),
            "Save again to retry.",
          ]
            .filter(Boolean)
            .join(" "),
        });
        return;
      }
      if (error instanceof LoopForeignWorkflowError) {
        reportForeignWorkflow();
        return;
      }
      if (requestErrorStatus(error) === 409) {
        // The server refused a write based on an older version of the loop.
        setHasRemoteUpdate(true);
        toast.error("Loop changed elsewhere", {
          description:
            "Cancel and reopen editing to see the latest version before saving.",
        });
        return;
      }
      toast.error(isEdit ? "Failed to save loop" : "Failed to create loop", {
        description:
          error instanceof UnsupportedLoopShapeError
            ? error.message
            : (hogFlowRequestDetail(error) ??
              (error instanceof Error ? error.message : undefined)),
      });
    }
  };

  const handleSubmit = async () => {
    if (hasRemoteUpdate) {
      toast.error("Loop changed elsewhere", {
        description: "Cancel and reopen editing before saving changes.",
      });
      return;
    }
    if (!canSubmit) return;
    if (workflowBacked) {
      await submitWorkflowLoop();
      return;
    }
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
      ownWriteUpdatedAtRef.current = saved.updated_at;
      track(
        isEdit ? ANALYTICS_EVENTS.LOOP_UPDATED : ANALYTICS_EVENTS.LOOP_CREATED,
        buildLoopSavedProps(saved),
      );
      const needsDetach =
        values.skill === null && loopSkillBundles(saved).length > 0;
      if (uploads || needsDetach) {
        try {
          await replaceSkillBundles.mutateAsync({
            loopId: saved.id,
            uploads: uploads ?? [],
          });
        } catch (error) {
          const description =
            error instanceof Error ? error.message : undefined;
          if (!isEdit) {
            // Roll the just-created loop back rather than leaving one that
            // fires `/skill-name` with no bundle behind it. If the rollback
            // itself fails, an orphaned loop exists — say so instead of
            // pretending nothing was created.
            try {
              await deleteLoop.mutateAsync(saved.id);
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
            return;
          }
          // Keep the form open with its state intact: saving again retries
          // both the loop write and the skill upload.
          toast.error("Loop saved, but updating its skill failed", {
            description: [description, "Save again to retry."]
              .filter(Boolean)
              .join(" "),
          });
          return;
        }
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

  if (isEmbedded) {
    return (
      <Flex
        direction="column"
        gap="4"
        className="rounded-(--radius-2) border border-border bg-(--gray-1) p-4"
      >
        {detachedSpace ? (
          <DetachedSpaceNotice spaceName={detachedSpace.name} />
        ) : null}

        <Step
          title="Prompt"
          description="Name it and write the prompt the agent runs each time."
        >
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
          {workflowBacked ? (
            <LoopWorkflowPromptFields
              values={values}
              disabled={isSubmitting}
              onPatch={patch}
            />
          ) : (
            <LoopInstructionsFields
              values={values}
              disabled={isSubmitting}
              onPatch={patch}
            />
          )}
        </Step>

        <Divider />

        <Step
          title="When"
          description={
            workflowBacked
              ? "Pick a schedule or a GitHub event. Every loop has one trigger."
              : "Add automatic triggers, or leave this manual-only."
          }
        >
          <LoopTriggerEditor
            triggers={values.triggers}
            triggerEndpointPath={triggerEndpointPath}
            disabled={isSubmitting}
            limits={workflowBacked ? WORKFLOW_TRIGGER_LIMITS : undefined}
            onChange={(triggers) => patch({ triggers })}
          />
        </Step>

        <Divider />

        <Step
          title="Options"
          description={
            workflowBacked
              ? "The repository the agent works in."
              : "Visibility, working context, and notifications."
          }
        >
          <div className="grid gap-4 md:grid-cols-2">
            {!workflowBacked ? (
              <Field
                label="Visibility"
                hint={
                  values.contextTarget
                    ? "Channel loops are team-visible."
                    : undefined
                }
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
            ) : null}

            <Field
              label="Base repository"
              hint={
                values.repositories.length > 1
                  ? `${values.repositories.length - 1} more attached.`
                  : "Optional for report-only loops."
              }
            >
              <LoopRepositoryPicker
                value={values.repositories[0] ?? null}
                disabled={isSubmitting}
                onChange={(repository) =>
                  setValues((prev) => ({
                    ...prev,
                    repositories: repository
                      ? [repository, ...prev.repositories.slice(1)]
                      : prev.repositories.slice(1),
                  }))
                }
              />
            </Field>

            {!workflowBacked ? (
              <Field
                label="Sandbox environment"
                hint="Applies its environment variables, network access, and image to every run."
              >
                <SettingsOptionSelect
                  value={values.sandboxEnvironmentId ?? ""}
                  options={sandboxEnvironmentOptions}
                  disabled={isSubmitting || environmentsLoading}
                  size="lg"
                  ariaLabel="Sandbox environment"
                  placeholder={
                    environmentsLoading ? "Loading environments…" : undefined
                  }
                  onValueChange={(value) =>
                    patch({ sandboxEnvironmentId: value || null })
                  }
                />
              </Field>
            ) : null}
          </div>

          {showContextField ? (
            <Field label="Context" hint="Attach runs to a sidebar channel.">
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
          ) : null}

          {!workflowBacked ? (
            <Field label="Notifications">
              <LoopNotificationsFields
                notifications={values.notifications}
                disabled={isSubmitting}
                onChange={(notifications) => patch({ notifications })}
              />
            </Field>
          ) : null}
        </Step>

        <Divider />

        <Step
          title="Advanced"
          description={
            workflowBacked
              ? "Model and reasoning."
              : "Behavior, model, and reasoning."
          }
        >
          {!workflowBacked ? (
            <Field label="Behavior">
              <LoopBehaviorFields
                behaviors={values.behaviors}
                disabled={isSubmitting}
                onChange={(behaviors) => patch({ behaviors })}
              />
            </Field>
          ) : null}
          <LoopModelFields
            adapter={values.runtimeAdapter}
            model={values.model}
            reasoningEffort={values.reasoningEffort}
            disabled={isSubmitting}
            adapterEditable={!workflowBacked}
            onAdapterChange={(runtimeAdapter) => patch({ runtimeAdapter })}
            onModelChange={(model) => patch({ model })}
            onReasoningEffortChange={(reasoningEffort) =>
              patch({ reasoningEffort })
            }
          />
        </Step>

        {hasRemoteUpdate ? (
          <Flex
            direction="column"
            gap="1"
            className="rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-3 py-2"
          >
            <Text className="font-medium text-(--amber-12) text-[12.5px]">
              This loop changed elsewhere
            </Text>
            <Text className="text-(--amber-11) text-[12px] leading-snug">
              Cancel and reopen editing before saving, so you don't overwrite
              newer settings.
            </Text>
          </Flex>
        ) : null}

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

  return (
    <Box className="flex h-full items-center justify-center p-6">
      <Flex
        direction="column"
        className="max-h-full w-full max-w-[640px] overflow-hidden rounded-(--radius-3) border border-border bg-(--color-panel-solid) shadow-xl"
      >
        <Box className="border-border border-b px-6 pt-5 pb-4">
          <Stepper current={step} complete={stepComplete} onSelect={setStep} />
        </Box>

        <Box className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
          {detachedSpace ? (
            <div className="mb-4">
              <DetachedSpaceNotice spaceName={detachedSpace.name} />
            </div>
          ) : null}

          {step === 0 ? (
            <Step
              title="What should this loop do?"
              description="Name it and write the prompt the agent runs on every fire."
            >
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
              {workflowBacked ? (
                <LoopWorkflowPromptFields
                  values={values}
                  disabled={isSubmitting}
                  onPatch={patch}
                />
              ) : (
                <LoopInstructionsFields
                  values={values}
                  disabled={isSubmitting}
                  onPatch={patch}
                />
              )}
            </Step>
          ) : null}

          {step === 1 ? (
            <Step
              title="When should it run?"
              description={
                workflowBacked
                  ? "Pick a schedule or a GitHub event. Every loop has one trigger, and you can also run a scheduled loop from its page."
                  : "A loop can have several triggers, and any one of them starts a run. With no triggers, you run it yourself from the loop's page."
              }
            >
              <LoopTriggerEditor
                triggers={values.triggers}
                triggerEndpointPath={triggerEndpointPath}
                disabled={isSubmitting}
                limits={workflowBacked ? WORKFLOW_TRIGGER_LIMITS : undefined}
                onChange={(triggers) => patch({ triggers })}
              />
            </Step>
          ) : null}

          {step === 2 ? (
            <Step
              title="Options"
              description={
                workflowBacked
                  ? "The repository the agent works in."
                  : "Who can see it and how you hear about runs."
              }
            >
              {!workflowBacked ? (
                <>
                  <Field
                    label="Visibility"
                    className="max-w-[340px]"
                    hint={
                      values.contextTarget
                        ? "Loops attached to a channel post runs to its shared feed, so they're visible to everyone on the project."
                        : undefined
                    }
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

                  <Divider />
                </>
              ) : null}

              {showContextField ? (
                <>
                  <Field
                    label="Context"
                    hint="A context is one of the channels in your sidebar. Attach this loop to a channel and its runs show up in that channel's feed; it can also keep the channel's context.md or a canvas up to date."
                  >
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

                  <Divider />
                </>
              ) : null}

              <Field
                label="Base repository"
                hint={
                  values.repositories.length > 1
                    ? `${values.repositories.length - 1} more ${
                        values.repositories.length === 2
                          ? "repository stays"
                          : "repositories stay"
                      } attached to this loop.`
                    : "The repository runs check out and work in. Optional. Leave empty for a report-only loop that works purely through connectors."
                }
              >
                <LoopRepositoryPicker
                  value={values.repositories[0] ?? null}
                  disabled={isSubmitting}
                  onChange={(repository) =>
                    setValues((prev) => ({
                      ...prev,
                      repositories: repository
                        ? [repository, ...prev.repositories.slice(1)]
                        : prev.repositories.slice(1),
                    }))
                  }
                />
              </Field>

              <Divider />

              {!workflowBacked ? (
                <>
                  <Field label="Notifications">
                    <LoopNotificationsFields
                      notifications={values.notifications}
                      disabled={isSubmitting}
                      onChange={(notifications) => patch({ notifications })}
                    />
                  </Field>

                  <Divider />
                </>
              ) : null}

              <Flex direction="column" gap="4">
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
                    {workflowBacked
                      ? "Model and reasoning"
                      : "Behavior, model and reasoning"}
                  </Text>
                </button>
                {showAdvanced ? (
                  <Flex direction="column" gap="4">
                    {!workflowBacked ? (
                      <Field label="Behavior">
                        <LoopBehaviorFields
                          behaviors={values.behaviors}
                          disabled={isSubmitting}
                          onChange={(behaviors) => patch({ behaviors })}
                        />
                      </Field>
                    ) : null}
                    <LoopModelFields
                      adapter={values.runtimeAdapter}
                      model={values.model}
                      reasoningEffort={values.reasoningEffort}
                      disabled={isSubmitting}
                      adapterEditable={!workflowBacked}
                      onAdapterChange={(runtimeAdapter) =>
                        patch({ runtimeAdapter })
                      }
                      onModelChange={(model) => patch({ model })}
                      onReasoningEffortChange={(reasoningEffort) =>
                        patch({ reasoningEffort })
                      }
                    />
                  </Flex>
                ) : null}
              </Flex>
            </Step>
          ) : null}

          {step === 3 ? (
            <Step
              title="Review"
              description="Check everything before you create the loop."
            >
              <ReviewList
                values={values}
                showContext={showContextField}
                workflowBacked={workflowBacked}
              />
            </Step>
          ) : null}
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

function Stepper({
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

function Step({
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

function Divider() {
  return <Box className="h-px bg-(--gray-4)" />;
}

function DetachedSpaceNotice({ spaceName }: { spaceName: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-3 py-2">
      <span className="font-medium text-(--amber-12) text-[12.5px]">
        This loop won't be attached to {channelDisplayLabel(spaceName)}
      </span>
      <span className="text-(--amber-11) text-[12px] leading-snug">
        Attaching loops to a space isn't available yet. You'll find it in the
        Loops list instead.
      </span>
    </div>
  );
}

function ReviewList({
  values,
  showContext,
  workflowBacked,
}: {
  values: LoopFormValues;
  showContext: boolean;
  workflowBacked: boolean;
}) {
  const reasoning = values.reasoningEffort ?? "auto";
  const channels = (["push", "email", "slack"] as const).filter(
    (channel) => values.notifications[channel]?.enabled,
  );

  return (
    <Flex
      direction="column"
      className="divide-y divide-(--gray-4) rounded-(--radius-3) border border-border"
    >
      <ReviewRow label="Name" value={values.name || "Not set"} />
      {!workflowBacked ? (
        <ReviewRow
          label="Visibility"
          value={values.visibility === "team" ? "Team" : "Personal"}
        />
      ) : null}
      <ReviewRow
        label="Prompt"
        value={
          values.skill
            ? buildSkillInstructions(values.skill.name, values.skillContext)
            : values.instructions.trim() || "No prompt"
        }
        multiline
      />
      {workflowBacked ? (
        <ReviewRow
          label="Skills"
          value={
            values.teamSkills.length > 0 ? values.teamSkills.join(", ") : "None"
          }
        />
      ) : null}
      <ReviewRow
        label="Model"
        value={[
          workflowBacked ? null : ADAPTER_LABELS[values.runtimeAdapter],
          formatLoopModel(values.runtimeAdapter, values.model),
          `${reasoning} reasoning`,
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      {showContext ? (
        <ReviewRow
          label="Context"
          value={describeContext(values.contextTarget)}
        />
      ) : null}
      <ReviewRow
        label="Base repository"
        value={
          values.repositories.length > 0
            ? values.repositories.map((repo) => repo.full_name).join(", ")
            : "None (report-only)"
        }
      />
      <ReviewRow
        label="Triggers"
        value={
          values.triggers.length === 0
            ? "Manual only"
            : values.triggers.map(summarizeTrigger).join(", ")
        }
      />
      {!workflowBacked ? (
        <>
          <ReviewRow
            label="Auto-fix PRs"
            value={isAutoFixEnabled(values.behaviors) ? "On" : "Off"}
          />
          <ReviewRow
            label="Notifications"
            value={channels.length === 0 ? "None" : channels.join(", ")}
          />
        </>
      ) : null}
    </Flex>
  );
}

function ReviewRow({
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
      <Text className="w-24 shrink-0 text-[12px] text-gray-10">{label}</Text>
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
  const targetLabel = channelDisplayLabel(target.name);
  return outputs.length > 0
    ? `${targetLabel} (${outputs.join(", ")})`
    : targetLabel;
}
