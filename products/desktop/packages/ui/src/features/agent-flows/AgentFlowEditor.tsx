import { ArrowDown, ArrowUp, Plus, Trash } from "@phosphor-icons/react";
import {
  Button,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Text,
  Textarea,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import {
  AGENT_FLOW_ROLES,
  type AgentFlowDefinition,
  type AgentFlowEffort,
  type AgentFlowRole,
  type AgentFlowStep,
  agentFlowSkillSlug,
  buildAgentFlowSkillBody,
  buildAgentFlowSkillDescription,
  serializeAgentFlowSkillFile,
} from "@posthog/shared";
import { type ReactNode, useMemo, useState } from "react";
import { FLOW_PRESETS, FlowRoleDots } from "./flowChips";
import { AGENT_FLOW_ROLE_META } from "./roleMeta";

export interface AgentFlowModelOption {
  provider: "posthog";
  id: string;
  name: string;
  isDefault: boolean;
  thinkingLevels: AgentFlowEffort[];
}

interface DraftStep {
  id: string;
  name: string;
  role: AgentFlowRole;
  modelId: string | null;
  effort: AgentFlowEffort | null;
  approvalAfter: boolean;
  instructions: string;
}

const ROLE_LABELS: Record<AgentFlowRole, string> = Object.fromEntries(
  Object.entries(AGENT_FLOW_ROLE_META).map(([role, meta]) => [
    role,
    meta.label,
  ]),
) as Record<AgentFlowRole, string>;

const EFFORT_LABELS: Record<AgentFlowEffort, string> = {
  off: "Off",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
};

function defaultEffort(
  model: AgentFlowModelOption | undefined,
): AgentFlowEffort | null {
  if (!model) return null;
  if (model.thinkingLevels.includes("high")) return "high";
  return model.thinkingLevels[0] ?? null;
}

function newDraftStep(
  role: AgentFlowRole,
  model: AgentFlowModelOption | undefined,
  approvalAfter = false,
): DraftStep {
  return {
    id: crypto.randomUUID(),
    name: ROLE_LABELS[role],
    role,
    modelId: model?.id ?? null,
    effort: defaultEffort(model),
    approvalAfter,
    instructions: "",
  };
}

function initialSteps(
  flow: AgentFlowDefinition | undefined,
  roles: AgentFlowRole[],
  model: AgentFlowModelOption | undefined,
): DraftStep[] {
  if (flow) {
    return flow.steps.map((step) => ({
      id: step.id,
      name: step.name,
      role: step.role,
      modelId: step.model.id,
      effort: step.effort,
      approvalAfter: step.approvalAfter,
      instructions: step.instructions ?? "",
    }));
  }
  return roles.map((role, index) =>
    newDraftStep(role, model, role === "planner" && index < roles.length - 1),
  );
}

export function AgentFlowEditor({
  models,
  flow,
  initialName,
  initialRoles,
  saving,
  secondaryActions,
  compact,
  onSave,
  onCancel,
}: {
  models: AgentFlowModelOption[];
  flow?: AgentFlowDefinition;
  initialName: string;
  initialRoles: AgentFlowRole[];
  saving?: boolean;
  secondaryActions?: ReactNode;
  /** Sidebar layout: stacked fields, no page heading, no Cancel button. */
  compact?: boolean;
  onSave: (flow: AgentFlowDefinition) => void;
  onCancel: () => void;
}) {
  const defaultModel = models.find((model) => model.isDefault) ?? models[0];
  const [name, setName] = useState(flow?.name ?? initialName);
  const [steps, setSteps] = useState<DraftStep[]>(() =>
    initialSteps(flow, initialRoles, defaultModel),
  );
  const [view, setView] = useState<"design" | "code">("design");

  const validSteps = useMemo(() => {
    const resolved: AgentFlowStep[] = [];
    for (const [stepIndex, step] of steps.entries()) {
      const model = models.find((item) => item.id === step.modelId);
      if (!model || !step.effort || !step.name.trim()) return null;
      if (!model.thinkingLevels.includes(step.effort)) return null;
      resolved.push({
        id: step.id,
        name: step.name.trim(),
        role: step.role,
        model: {
          provider: model.provider,
          id: model.id,
          name: model.name,
        },
        effort: step.effort,
        approvalAfter: stepIndex < steps.length - 1 && step.approvalAfter,
        instructions: step.instructions.trim() || undefined,
      });
    }
    return resolved;
  }, [models, steps]);

  const draftFlow: AgentFlowDefinition | null = validSteps
    ? {
        id: flow?.id ?? "draft",
        name: name.trim() || "Untitled flow",
        steps: validSteps,
      }
    : null;

  const canSave =
    name.trim().length > 0 &&
    steps.length >= 2 &&
    steps.length <= 6 &&
    validSteps !== null;

  const updateStep = (stepId: string, patch: Partial<DraftStep>) => {
    setSteps((current) =>
      current.map((step) =>
        step.id === stepId ? { ...step, ...patch } : step,
      ),
    );
  };

  const moveStep = (stepIndex: number, direction: -1 | 1) => {
    setSteps((current) => {
      const target = stepIndex + direction;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[stepIndex], next[target]] = [next[target], next[stepIndex]];
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-3">
        {compact ? null : (
          <div>
            <h2 className="font-semibold text-[18px] text-gray-12">
              {flow ? "Edit flow" : "New flow"}
            </h2>
            <Text size="xs" variant="muted">
              Steps run from top to bottom. Each step uses its exact Pi model
              and effort.
            </Text>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          <ToggleGroup
            value={[view]}
            onValueChange={(values: string[]) => {
              const next = values[0];
              if (next === "design" || next === "code") setView(next);
            }}
            aria-label="Editor view"
          >
            <ToggleGroupItem value="design">Design</ToggleGroupItem>
            <ToggleGroupItem value="code">Code</ToggleGroupItem>
          </ToggleGroup>
          {secondaryActions}
          {compact ? null : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onCancel}
            >
              Cancel
            </Button>
          )}
          <Button
            type="button"
            variant="primary"
            size="sm"
            loading={saving}
            disabled={!canSave || saving}
            data-attr="agent-flow-save"
            onClick={() => {
              if (!validSteps || saving) return;
              onSave({
                id: flow?.id ?? crypto.randomUUID(),
                name: name.trim(),
                steps: validSteps,
              });
            }}
          >
            Save flow
          </Button>
        </div>
      </div>

      {!flow && view === "design" ? (
        <div className="flex flex-col gap-1.5">
          <Text size="xs" className="font-medium text-gray-12">
            Start from a preset
          </Text>
          <div
            className={`grid grid-cols-1 gap-2 ${compact ? "" : "md:grid-cols-3"}`}
          >
            {FLOW_PRESETS.map((preset) => (
              <button
                key={preset.name}
                type="button"
                className="flex flex-col items-start gap-1 rounded-lg border border-gray-5 bg-gray-1 p-3 text-left transition-colors hover:border-gray-7 hover:bg-gray-2"
                onClick={() => {
                  setName(preset.name);
                  setSteps(initialSteps(undefined, preset.roles, defaultModel));
                }}
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="font-medium text-[13px] text-gray-12">
                    {preset.name}
                  </span>
                  <FlowRoleDots roles={preset.roles} />
                </span>
                <span className="text-[12px] text-gray-10">
                  {preset.description}
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {view === "design" ? (
        <>
          <div className="flex max-w-md flex-col gap-1.5">
            <Text size="xs" className="font-medium text-gray-12">
              Flow name
            </Text>
            <Input
              value={name}
              onChange={(event) => setName(event.currentTarget.value)}
              placeholder="Planner and executor"
              aria-label="Flow name"
              data-attr="agent-flow-name"
            />
          </div>

          <div
            className="rounded-xl border border-gray-4 p-6"
            style={{
              backgroundImage:
                "radial-gradient(var(--gray-a4) 1px, transparent 1px)",
              backgroundSize: "16px 16px",
            }}
          >
            <div className="mx-auto flex w-full max-w-2xl flex-col">
              {steps.map((step, stepIndex) => {
                const selectedModel = models.find(
                  (model) => model.id === step.modelId,
                );
                const effortOptions = selectedModel?.thinkingLevels ?? [];
                const roleMeta = AGENT_FLOW_ROLE_META[step.role];
                const RoleIcon = roleMeta.icon;
                return (
                  <div key={step.id} className="flex flex-col">
                    <div className="overflow-hidden rounded-xl border border-gray-6 bg-gray-1 shadow-xs">
                      <div className="flex items-center justify-between gap-2 border-gray-4 border-b bg-gray-2 px-3 py-2">
                        <div className="flex min-w-0 items-center gap-2">
                          <span
                            className={`flex size-6 shrink-0 items-center justify-center rounded-md ${roleMeta.chipClass}`}
                          >
                            <RoleIcon size={14} weight="bold" />
                          </span>
                          <Text
                            size="sm"
                            className="truncate font-semibold text-gray-12"
                          >
                            {step.name || "Step"}
                          </Text>
                          <span className="shrink-0 text-[11px] text-gray-9">
                            Step {stepIndex + 1}
                          </span>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <Button
                            type="button"
                            variant="link-muted"
                            size="icon-sm"
                            aria-label={`Move ${step.name} up`}
                            disabled={stepIndex === 0}
                            onClick={() => moveStep(stepIndex, -1)}
                          >
                            <ArrowUp size={14} />
                          </Button>
                          <Button
                            type="button"
                            variant="link-muted"
                            size="icon-sm"
                            aria-label={`Move ${step.name} down`}
                            disabled={stepIndex === steps.length - 1}
                            onClick={() => moveStep(stepIndex, 1)}
                          >
                            <ArrowDown size={14} />
                          </Button>
                          <Button
                            type="button"
                            variant="link-muted"
                            size="icon-sm"
                            aria-label={`Remove ${step.name}`}
                            disabled={steps.length <= 2}
                            onClick={() =>
                              setSteps((current) =>
                                current.filter((item) => item.id !== step.id),
                              )
                            }
                          >
                            <Trash size={14} />
                          </Button>
                        </div>
                      </div>

                      <div className="flex flex-col gap-3 px-3 py-3">
                        <div
                          className={`grid grid-cols-1 gap-3 ${compact ? "" : "md:grid-cols-3"}`}
                        >
                          <div className="flex flex-col gap-1.5">
                            <Text
                              size="xs"
                              className="font-medium text-gray-12"
                            >
                              Role
                            </Text>
                            <Select
                              value={step.role}
                              onValueChange={(value) => {
                                if (!value) return;
                                const role = value as AgentFlowRole;
                                updateStep(step.id, {
                                  role,
                                  name: ROLE_LABELS[role],
                                });
                              }}
                              items={AGENT_FLOW_ROLES.map((role) => ({
                                value: role,
                                label: ROLE_LABELS[role],
                              }))}
                            >
                              <SelectTrigger size="sm" aria-label="Agent role">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {AGENT_FLOW_ROLES.map((role) => (
                                  <SelectItem key={role} value={role}>
                                    {ROLE_LABELS[role]}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>

                          <div className="flex flex-col gap-1.5">
                            <Text
                              size="xs"
                              className="font-medium text-gray-12"
                            >
                              Model
                            </Text>
                            <Select
                              value={step.modelId}
                              onValueChange={(value) => {
                                const model = models.find(
                                  (item) => item.id === value,
                                );
                                updateStep(step.id, {
                                  modelId: value,
                                  effort: defaultEffort(model),
                                });
                              }}
                              items={models.map((model) => ({
                                value: model.id,
                                label: model.name,
                              }))}
                            >
                              <SelectTrigger size="sm" aria-label="Pi model">
                                <SelectValue placeholder="Select a model" />
                              </SelectTrigger>
                              <SelectContent>
                                {models.map((model) => (
                                  <SelectItem key={model.id} value={model.id}>
                                    {model.name}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>

                          <div className="flex flex-col gap-1.5">
                            <Text
                              size="xs"
                              className="font-medium text-gray-12"
                            >
                              Effort
                            </Text>
                            <Select
                              value={step.effort}
                              onValueChange={(value) => {
                                if (!value) return;
                                updateStep(step.id, {
                                  effort: value as AgentFlowEffort,
                                });
                              }}
                              items={effortOptions.map((effort) => ({
                                value: effort,
                                label: EFFORT_LABELS[effort],
                              }))}
                            >
                              <SelectTrigger
                                size="sm"
                                aria-label="Reasoning effort"
                              >
                                <SelectValue placeholder="Select effort" />
                              </SelectTrigger>
                              <SelectContent>
                                {effortOptions.map((effort) => (
                                  <SelectItem key={effort} value={effort}>
                                    {EFFORT_LABELS[effort]}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        </div>

                        <div className="flex flex-col gap-1.5">
                          <Text size="xs" className="font-medium text-gray-12">
                            Step instructions
                          </Text>
                          <Textarea
                            value={step.instructions}
                            onChange={(event) =>
                              updateStep(step.id, {
                                instructions: event.currentTarget.value,
                              })
                            }
                            rows={2}
                            placeholder="Optional instructions for this step"
                            aria-label={`${step.name} instructions`}
                          />
                        </div>
                      </div>
                    </div>

                    {stepIndex < steps.length - 1 ? (
                      <div
                        className="flex flex-col items-center gap-1 py-1.5"
                        title="Show this step's handoff and wait for approval before the next step."
                      >
                        <div className="h-3 w-px bg-gray-7" />
                        <div
                          className={`flex items-center gap-2 rounded-full border px-3 py-1 ${
                            step.approvalAfter
                              ? "border-blue-6 bg-blue-2"
                              : "border-gray-6 bg-gray-1"
                          }`}
                        >
                          <Switch
                            checked={step.approvalAfter}
                            aria-label={`Review the handoff after ${step.name}`}
                            onCheckedChange={(checked) =>
                              updateStep(step.id, { approvalAfter: checked })
                            }
                          />
                          <Text
                            size="xs"
                            className={
                              step.approvalAfter
                                ? "text-blue-11"
                                : "text-gray-10"
                            }
                          >
                            Review handoff
                          </Text>
                        </div>
                        <div className="h-3 w-px bg-gray-7" />
                      </div>
                    ) : null}
                  </div>
                );
              })}

              {steps.length < 6 ? (
                <>
                  <div className="flex flex-col items-center py-1.5">
                    <div className="h-4 w-px bg-gray-7" />
                  </div>
                  <button
                    type="button"
                    className="flex items-center justify-center gap-2 rounded-xl border border-gray-6 border-dashed px-4 py-3 text-gray-11 text-sm transition-colors hover:bg-gray-2"
                    onClick={() =>
                      setSteps((current) => [
                        ...current,
                        newDraftStep("executor", defaultModel),
                      ])
                    }
                  >
                    <Plus size={14} />
                    Add step
                  </button>
                </>
              ) : null}
            </div>
          </div>
        </>
      ) : draftFlow ? (
        <div className="flex flex-col gap-4">
          {[
            {
              label: `~/.claude/skills/${agentFlowSkillSlug(draftFlow.name)}/SKILL.md`,
              text: `---\nname: ${agentFlowSkillSlug(draftFlow.name)}\ndescription: ${buildAgentFlowSkillDescription(draftFlow)}\n---\n\n${buildAgentFlowSkillBody(draftFlow)}`,
            },
            {
              label: `~/.claude/skills/${agentFlowSkillSlug(draftFlow.name)}/flow.json`,
              text: serializeAgentFlowSkillFile(draftFlow),
            },
          ].map((file) => (
            <div key={file.label} className="flex flex-col gap-1.5">
              <Text size="xs" className="font-mono text-gray-10">
                {file.label}
              </Text>
              <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-gray-5 bg-gray-1 p-3 font-mono text-[12px] text-gray-12 leading-relaxed">
                {file.text}
              </pre>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-gray-5 border-dashed p-4 text-[13px] text-gray-10">
          Finish the steps in the Design view to see the generated skill files.
        </div>
      )}
    </div>
  );
}
