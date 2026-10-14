import {
  ArrowLeft,
  ArrowRight,
  CaretRight,
  Check,
} from "@phosphor-icons/react";
import { requestErrorStatus } from "@posthog/api-client/fetcher";
import { hogFlowRequestDetail } from "@posthog/api-client/hogFlowLoops";
import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import { Button, cn, Input, Textarea } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import type { LoopSchemas } from "@posthog/ui/features/loops/loopSchemas";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToLoopDetail,
  navigateToLoops,
} from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useLoopHogFlow } from "../hooks/useLoop";
import { useCreateLoop, useUpdateLoop } from "../hooks/useLoopMutations";
import { buildLoopSavedProps } from "../loopAnalytics";
import { summarizeTrigger } from "../loopDisplay";
import { useLoopDraftStore } from "../loopDraftStore";
import {
  emptyLoopFormValues,
  isLoopFormValid,
  isTriggerListValid,
  type LoopContextTargetDraft,
  type LoopFormValues,
  loopToFormValues,
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
import { LoopContextFields } from "./LoopContextFields";
import { Field } from "./LoopFormPrimitives";
import { LoopHeaderTitle } from "./LoopHeaderTitle";
import { LoopModelFields } from "./LoopModelFields";
import { LoopRepositoryPicker } from "./LoopRepositoryPicker";
import { LoopSpaceBreadcrumb } from "./LoopSpaceBreadcrumb";
import { LoopTriggerEditor } from "./LoopTriggerEditor";
import { LoopWorkflowPromptFields } from "./LoopWorkflowPromptFields";

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
  const values = { ...loopToFormValues(loop), teamSkills };
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
  frame?: "page" | "dialog";
  onCancel?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  onSaved?: (loop: LoopSchemas.Loop) => void;
}

export function LoopForm({
  loop,
  variant = "wizard",
  frame = "page",
  onCancel,
  onDirtyChange,
  onSaved,
}: LoopFormProps) {
  const isEdit = !!loop;
  const isEmbedded = variant === "embedded";
  // The loop prop is a projection of this same cached workflow, so it is
  // already loaded whenever `loop` is; the raw flow carries the team skills
  // and the schedule row the save needs to reconcile.
  const { data: hogFlow } = useLoopHogFlow(loop?.id);
  const teamSkills = useMemo(
    () => (hogFlow ? hogFlowTeamSkills(hogFlow) : []),
    [hogFlow],
  );
  // One-shot prefill from the landing prompt, a template, or a space; merged
  // over the blank defaults. Read (not consumed) here, then cleared in the
  // effect below so the manual "New loop" button always opens a blank form.
  const [prefill] = useState(() =>
    loop ? null : useLoopDraftStore.getState().prefill,
  );
  const [values, setValues] = useState<LoopFormValues>(() => {
    if (loop) {
      return { ...loopToFormValues(loop), teamSkills };
    }
    return { ...emptyLoopFormValues(), ...(prefill ?? {}) };
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
  const showContextField = channelsEnabled || !!values.contextTarget;

  const createLoop = useCreateLoop();
  const updateLoop = useUpdateLoop(loop?.id ?? "");
  const isSubmitting = createLoop.isPending || updateLoop.isPending;
  const canSubmit =
    isLoopFormValid(values) && !isSubmitting && !hasRemoteUpdate;

  // Per-step gate for the Next button. The final Create button is gated on the
  // whole form being valid, so jumping between steps can't submit a bad loop.
  const stepComplete = [
    !!values.name.trim() && !!values.instructions.trim(),
    isTriggerListValid(values.triggers),
    true,
    isLoopFormValid(values),
  ];
  const isLastStep = step === STEPS.length - 1;

  // Building a loop for a space keeps a way back to it, attached or not;
  // without one the header still names the scene, it just has no parent to
  // offer.
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
    frame !== "dialog",
  );

  const patch = (next: Partial<LoopFormValues>) =>
    setValues((prev) => ({ ...prev, ...next }));

  const handleCancel = () => {
    if (onCancel) {
      onCancel();
      return;
    }
    if (isEdit) {
      navigateToLoopDetail(loop.id, {
        channelId: loop.context_target?.channel_id,
      });
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

  const handleSubmit = async () => {
    if (hasRemoteUpdate) {
      toast.error("Loop changed elsewhere", {
        description: "Cancel and reopen editing before saving changes.",
      });
      return;
    }
    if (!canSubmit) return;
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
          ? await updateLoop.mutateAsync({ values, existing: hogFlow })
          : await createLoop.mutateAsync({ values, enabled: true });
      ownWriteUpdatedAtRef.current = saved.updated_at;
      track(
        isEdit ? ANALYTICS_EVENTS.LOOP_UPDATED : ANALYTICS_EVENTS.LOOP_CREATED,
        buildLoopSavedProps(saved),
      );
      if (onSaved) {
        onSaved(saved);
      } else {
        navigateToLoopDetail(saved.id, {
          channelId: saved.context_target?.channel_id,
        });
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

  if (isEmbedded) {
    return (
      <div className="flex flex-col gap-4 rounded-(--radius-2) border border-border bg-(--gray-1) p-4">
        <Step
          title="Prompt"
          description="Name it and write the prompt the agent runs each time."
        >
          <Field label="Name" required>
            <Input
              value={values.name}
              placeholder="Daily standup summary"
              disabled={isSubmitting}
              onChange={(e) => patch({ name: e.target.value })}
            />
          </Field>
          <Field label="Description">
            <Textarea
              className="min-h-[72px] text-[13px] leading-relaxed"
              value={values.description}
              placeholder="A short summary shown on the Loops list"
              disabled={isSubmitting}
              onChange={(e) => patch({ description: e.target.value })}
            />
          </Field>
          <LoopWorkflowPromptFields
            values={values}
            disabled={isSubmitting}
            onPatch={patch}
          />
        </Step>

        <Divider />

        <Step
          title="When"
          description="Pick a schedule or a GitHub event. Every loop has one trigger."
        >
          <LoopTriggerEditor
            triggers={values.triggers}
            disabled={isSubmitting}
            onChange={(triggers) => patch({ triggers })}
          />
        </Step>

        <Divider />

        <Step title="Options" description="The repository the agent works in.">
          <div className="grid gap-4 md:grid-cols-2">
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
          </div>

          {showContextField ? (
            <Field label="Context" hint="Attach runs to a sidebar channel.">
              <LoopContextFields
                value={values.contextTarget}
                disabled={isSubmitting}
                onChange={(contextTarget) => patch({ contextTarget })}
              />
            </Field>
          ) : null}
        </Step>

        <Divider />

        <Step title="Advanced" description="Model and reasoning.">
          <LoopModelFields
            adapter={values.runtimeAdapter}
            model={values.model}
            reasoningEffort={values.reasoningEffort}
            disabled={isSubmitting}
            onModelChange={(model) => patch({ model })}
            onReasoningEffortChange={(reasoningEffort) =>
              patch({ reasoningEffort })
            }
          />
        </Step>

        {hasRemoteUpdate ? (
          <div className="flex flex-col gap-1 rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-3 py-2">
            <span className="font-medium text-(--amber-12) text-[12.5px]">
              This loop changed elsewhere
            </span>
            <span className="text-(--amber-11) text-[12px] leading-snug">
              Cancel and reopen editing before saving, so you don't overwrite
              newer settings.
            </span>
          </div>
        ) : null}

        <div className="sticky bottom-0 z-10 flex items-center justify-end gap-2 border-border border-t bg-(--gray-1) py-4">
          <Button
            type="button"
            variant="outline"
            size="default"
            disabled={isSubmitting}
            onClick={handleCancel}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            size="default"
            loading={isSubmitting}
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            Save changes
          </Button>
        </div>
      </div>
    );
  }

  const card = (
    <div
      className={cn(
        "flex flex-col",
        frame === "dialog"
          ? "min-h-0 w-full flex-1 overflow-hidden"
          : "max-h-full w-full max-w-[640px] overflow-hidden rounded-(--radius-3) border border-border bg-(--color-panel-solid) shadow-xl",
      )}
    >
      <div className="border-border border-b px-6 pt-5 pb-4">
        <Stepper current={step} complete={stepComplete} onSelect={setStep} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        {step === 0 ? (
          <Step
            title="What should this loop do?"
            description="Name it and write the prompt the agent runs on every fire."
          >
            <Field label="Name" required>
              <Input
                value={values.name}
                placeholder="Daily standup summary"
                disabled={isSubmitting}
                autoFocus
                onChange={(e) => patch({ name: e.target.value })}
              />
            </Field>
            <Field label="Description">
              <Input
                value={values.description}
                placeholder="A short summary shown on the Loops list"
                disabled={isSubmitting}
                onChange={(e) => patch({ description: e.target.value })}
              />
            </Field>
            <LoopWorkflowPromptFields
              values={values}
              disabled={isSubmitting}
              onPatch={patch}
            />
          </Step>
        ) : null}

        {step === 1 ? (
          <Step
            title="When should it run?"
            description="Pick a schedule or a GitHub event. Every loop has one trigger, and you can also run a scheduled loop from its page."
          >
            <LoopTriggerEditor
              triggers={values.triggers}
              disabled={isSubmitting}
              onChange={(triggers) => patch({ triggers })}
            />
          </Step>
        ) : null}

        {step === 2 ? (
          <Step
            title="Options"
            description="The repository the agent works in."
          >
            {showContextField ? (
              <>
                <Field
                  label="Context"
                  hint="A context is one of the channels in your sidebar. Attach this loop to a channel and its runs show up in that channel's feed."
                >
                  <LoopContextFields
                    value={values.contextTarget}
                    disabled={isSubmitting}
                    onChange={(contextTarget) => patch({ contextTarget })}
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

            <div className="flex flex-col gap-4">
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
                <span className="font-medium text-[12.5px] text-gray-11">
                  Advanced
                </span>
                <span className="text-[11.5px] text-gray-9">
                  Model and reasoning
                </span>
              </button>
              {showAdvanced ? (
                <div className="flex flex-col gap-4">
                  <LoopModelFields
                    adapter={values.runtimeAdapter}
                    model={values.model}
                    reasoningEffort={values.reasoningEffort}
                    disabled={isSubmitting}
                    onModelChange={(model) => patch({ model })}
                    onReasoningEffortChange={(reasoningEffort) =>
                      patch({ reasoningEffort })
                    }
                  />
                </div>
              ) : null}
            </div>
          </Step>
        ) : null}

        {step === 3 ? (
          <Step
            title="Review"
            description="Check everything before you create the loop."
          >
            <ReviewList values={values} showContext={showContextField} />
          </Step>
        ) : null}
      </div>

      <div className="flex items-center justify-between gap-3 border-border border-t px-5 py-3">
        <Button
          type="button"
          variant="outline"
          size="default"
          disabled={isSubmitting}
          onClick={handleCancel}
        >
          Cancel
        </Button>
        <div className="flex shrink-0 gap-2">
          {step > 0 ? (
            <Button
              type="button"
              variant="outline"
              size="default"
              disabled={isSubmitting}
              onClick={() => setStep((s) => s - 1)}
            >
              <ArrowLeft size={13} />
              Back
            </Button>
          ) : null}
          {isLastStep ? (
            <Button
              type="button"
              variant="primary"
              size="default"
              loading={isSubmitting}
              disabled={!canSubmit}
              onClick={() => void handleSubmit()}
            >
              {isEdit ? "Save changes" : "Create loop"}
            </Button>
          ) : (
            <Button
              type="button"
              variant="primary"
              size="default"
              disabled={!stepComplete[step] || isSubmitting}
              onClick={() => setStep((s) => s + 1)}
            >
              Next
              <ArrowRight size={13} />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
  if (frame === "dialog") return card;
  return (
    <div className="flex h-full items-center justify-center p-6">{card}</div>
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
    <div className="flex items-center gap-0">
      {STEPS.map((label, index) => {
        const isCurrent = index === current;
        const isDone = index < current && complete[index];
        const canSelect =
          index <= current || complete.slice(current, index).every(Boolean);
        return (
          <div
            className="flex min-w-0 flex-1 items-center last:flex-none"
            key={label}
          >
            <button
              type="button"
              disabled={!canSelect}
              onClick={() => {
                if (canSelect) onSelect(index);
              }}
              className="flex min-w-0 cursor-pointer items-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <div
                className={cn(
                  "flex items-center justify-center",
                  `size-5 shrink-0 rounded-full border font-medium text-[11px] ${
                    isCurrent
                      ? "border-(--accent-9) bg-(--accent-9) text-(--accent-contrast)"
                      : isDone
                        ? "border-(--accent-7) bg-(--accent-3) text-(--accent-11)"
                        : "border-(--gray-7) text-gray-11"
                  }`,
                )}
              >
                {isDone ? <Check size={12} weight="bold" /> : index + 1}
              </div>
              <span
                className={`truncate text-[12.5px] ${
                  isCurrent ? "font-medium text-gray-12" : "text-gray-11"
                }`}
              >
                {label}
              </span>
            </button>
            {index < STEPS.length - 1 ? (
              <div className="mx-2 h-px min-w-4 flex-1 bg-(--gray-5)" />
            ) : null}
          </div>
        );
      })}
    </div>
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
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <span className="font-medium text-[15px] text-gray-12">{title}</span>
        <span className="text-[12.5px] text-gray-10 leading-snug">
          {description}
        </span>
      </div>
      {children}
    </div>
  );
}

function Divider() {
  return <div className="h-px bg-(--gray-4)" />;
}

function ReviewList({
  values,
  showContext,
}: {
  values: LoopFormValues;
  showContext: boolean;
}) {
  const reasoning = values.reasoningEffort ?? "auto";

  return (
    <div className="flex flex-col divide-y divide-(--gray-4) rounded-(--radius-3) border border-border">
      <ReviewRow label="Name" value={values.name || "Not set"} />
      <ReviewRow
        label="Prompt"
        value={values.instructions.trim() || "No prompt"}
        multiline
      />
      <ReviewRow
        label="Skills"
        value={
          values.teamSkills.length > 0 ? values.teamSkills.join(", ") : "None"
        }
      />
      <ReviewRow
        label="Model"
        value={[
          formatLoopModel(values.runtimeAdapter, values.model),
          `${reasoning} reasoning`,
        ].join(" · ")}
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
    </div>
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
    <div className="flex gap-4 px-3 py-2.5">
      <span className="w-24 shrink-0 text-[12px] text-gray-10">{label}</span>
      <span
        className={`min-w-0 flex-1 text-[12.5px] text-gray-12 ${
          multiline ? "whitespace-pre-wrap" : "truncate"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function describeContext(target: LoopContextTargetDraft | null): string {
  if (!target) return "Not attached to a channel";
  return `${channelDisplayLabel(target.name)} (feed)`;
}
