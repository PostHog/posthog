import {
  ArrowDownIcon,
  ArrowUpIcon,
  CaretDownIcon,
  CheckIcon,
  DotsThreeIcon,
  FlowArrowIcon,
  PlusIcon,
  TrashIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
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
import { FLOW_PRESETS } from "./flowChips";
import { AGENT_FLOW_EFFORT_LABELS, AGENT_FLOW_ROLE_META } from "./roleMeta";

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
  menuItems,
  onSave,
  onClose,
}: {
  models: AgentFlowModelOption[];
  flow?: AgentFlowDefinition;
  initialName: string;
  initialRoles: AgentFlowRole[];
  saving?: boolean;
  menuItems?: ReactNode;
  onSave: (flow: AgentFlowDefinition) => void;
  onClose: () => void;
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

  const flowKey = (value: AgentFlowDefinition) =>
    JSON.stringify({ name: value.name.trim(), steps: value.steps });
  const isDirty =
    !flow || draftFlow === null || flowKey(draftFlow) !== flowKey(flow);

  const canSave =
    name.trim().length > 0 &&
    steps.length >= 2 &&
    steps.length <= 6 &&
    validSteps !== null &&
    isDirty;

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
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1.5 border-gray-4 border-b px-2 py-1.5">
        <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-violet-3 text-violet-11">
          <FlowArrowIcon size={14} weight="duotone" />
        </span>
        <input
          className="min-w-0 flex-1 rounded bg-transparent px-1 py-0.5 font-semibold text-[13px] text-gray-12 outline-none transition-colors placeholder:font-normal placeholder:text-gray-9 hover:bg-gray-3 focus:bg-gray-2"
          value={name}
          onChange={(event) => setName(event.currentTarget.value)}
          placeholder="Name this flow"
          aria-label="Flow name"
          data-attr="agent-flow-name"
        />
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
          Save
        </Button>
        {menuItems ? (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  type="button"
                  variant="link-muted"
                  size="icon-sm"
                  aria-label="More actions"
                >
                  <DotsThreeIcon size={16} weight="bold" />
                </Button>
              }
            />
            <DropdownMenuContent align="end" className="min-w-[200px]">
              {menuItems}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
        <Button
          type="button"
          variant="link-muted"
          size="icon-sm"
          aria-label="Close"
          onClick={onClose}
        >
          <XIcon size={14} />
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center border-gray-4 border-b bg-gray-1 px-3 py-1.5">
          <ToggleGroup
            value={[view]}
            onValueChange={(next: string[]) => {
              const selected = next[0];
              if (selected) setView(selected as "design" | "code");
            }}
            aria-label="Flow view"
            className="gap-1"
          >
            <ToggleGroupItem value="design" size="sm" variant="outline">
              Steps
            </ToggleGroupItem>
            <ToggleGroupItem value="code" size="sm" variant="outline">
              Code
            </ToggleGroupItem>
          </ToggleGroup>
          {flow ? null : (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="ml-auto"
                  >
                    Presets
                  </Button>
                }
              />
              <DropdownMenuContent align="end" className="min-w-[220px]">
                {FLOW_PRESETS.map((preset) => (
                  <DropdownMenuItem
                    key={preset.name}
                    onClick={() => {
                      setName(preset.name);
                      setSteps(
                        initialSteps(undefined, preset.roles, defaultModel),
                      );
                    }}
                  >
                    {preset.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
        {view === "design" ? (
          <div
            className="min-h-0 flex-1 overflow-y-auto p-3"
            style={{
              backgroundImage:
                "radial-gradient(var(--gray-a4) 1px, transparent 1px)",
              backgroundSize: "16px 16px",
            }}
          >
            {steps.map((step, stepIndex) => {
              const selectedModel = models.find(
                (model) => model.id === step.modelId,
              );
              const effortOptions = selectedModel?.thinkingLevels ?? [];
              const roleMeta = AGENT_FLOW_ROLE_META[step.role];
              const RoleIcon = roleMeta.icon;
              return (
                <div key={step.id} className="flex flex-col">
                  <div className="group overflow-hidden rounded-lg border border-gray-6 bg-gray-1 shadow-xs">
                    <div className="flex items-center gap-1 border-gray-4 border-b bg-gray-2 py-1 pr-1 pl-1.5">
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          render={
                            <button
                              type="button"
                              aria-label={`Change the role of step ${stepIndex + 1}`}
                              className="flex min-w-0 items-center gap-1.5 rounded px-1 py-0.5 transition-colors hover:bg-gray-4"
                            >
                              <span
                                className={`flex size-5 shrink-0 items-center justify-center rounded ${roleMeta.chipClass}`}
                              >
                                <RoleIcon size={12} weight="bold" />
                              </span>
                              <span className="truncate font-semibold text-[13px] text-gray-12">
                                {step.name || roleMeta.label}
                              </span>
                              <CaretDownIcon
                                size={10}
                                className="shrink-0 text-gray-9"
                              />
                            </button>
                          }
                        />
                        <DropdownMenuContent align="start">
                          {AGENT_FLOW_ROLES.map((role) => {
                            const meta = AGENT_FLOW_ROLE_META[role];
                            const Icon = meta.icon;
                            return (
                              <DropdownMenuItem
                                key={role}
                                onClick={() =>
                                  updateStep(step.id, {
                                    role,
                                    name: ROLE_LABELS[role],
                                  })
                                }
                              >
                                <Icon size={13} />
                                {meta.label}
                                {role === step.role ? (
                                  <CheckIcon
                                    size={12}
                                    className="ml-auto text-gray-10"
                                  />
                                ) : null}
                              </DropdownMenuItem>
                            );
                          })}
                        </DropdownMenuContent>
                      </DropdownMenu>

                      <span className="ml-auto shrink-0 px-1 text-[11px] text-gray-9 tabular-nums">
                        {stepIndex + 1}/{steps.length}
                      </span>
                      <div className="flex shrink-0 items-center opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                        <Button
                          type="button"
                          variant="link-muted"
                          size="icon-sm"
                          aria-label={`Move ${step.name} up`}
                          disabled={stepIndex === 0}
                          onClick={() => moveStep(stepIndex, -1)}
                        >
                          <ArrowUpIcon size={13} />
                        </Button>
                        <Button
                          type="button"
                          variant="link-muted"
                          size="icon-sm"
                          aria-label={`Move ${step.name} down`}
                          disabled={stepIndex === steps.length - 1}
                          onClick={() => moveStep(stepIndex, 1)}
                        >
                          <ArrowDownIcon size={13} />
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
                          <TrashIcon size={13} />
                        </Button>
                      </div>
                    </div>

                    <div className="flex flex-col gap-1.5 p-1.5">
                      <div className="grid grid-cols-2 gap-1.5">
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
                            <SelectValue placeholder="Model" />
                          </SelectTrigger>
                          <SelectContent>
                            {models.map((model) => (
                              <SelectItem key={model.id} value={model.id}>
                                {model.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>

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
                            label: AGENT_FLOW_EFFORT_LABELS[effort],
                          }))}
                        >
                          <SelectTrigger
                            size="sm"
                            aria-label="Reasoning effort"
                          >
                            <SelectValue placeholder="Effort" />
                          </SelectTrigger>
                          <SelectContent>
                            {effortOptions.map((effort) => (
                              <SelectItem key={effort} value={effort}>
                                {AGENT_FLOW_EFFORT_LABELS[effort]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      <Textarea
                        value={step.instructions}
                        onChange={(event) =>
                          updateStep(step.id, {
                            instructions: event.currentTarget.value,
                          })
                        }
                        rows={1}
                        className="field-sizing-content max-h-40 min-h-7"
                        placeholder="Extra instructions (optional)"
                        aria-label={`${step.name} instructions`}
                      />
                    </div>
                  </div>

                  {stepIndex < steps.length - 1 ? (
                    <div
                      className="flex flex-col items-center gap-1 py-1"
                      title="Show this step's handoff and wait for approval before the next step."
                    >
                      <div className="h-2.5 w-px bg-gray-7" />
                      <div
                        className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 ${
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
                        <span
                          className={`text-[11px] ${
                            step.approvalAfter ? "text-blue-11" : "text-gray-10"
                          }`}
                        >
                          Review handoff
                        </span>
                      </div>
                      <div className="h-2.5 w-px bg-gray-7" />
                    </div>
                  ) : null}
                </div>
              );
            })}

            {steps.length < 6 ? (
              <>
                <div className="flex flex-col items-center py-1">
                  <div className="h-3 w-px bg-gray-7" />
                </div>
                <button
                  type="button"
                  className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-gray-6 border-dashed px-3 py-2 text-[12px] text-gray-11 transition-colors hover:bg-gray-2"
                  onClick={() =>
                    setSteps((current) => [
                      ...current,
                      newDraftStep("executor", defaultModel),
                    ])
                  }
                >
                  <PlusIcon size={13} />
                  Add step
                </button>
              </>
            ) : null}
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {draftFlow ? (
              <div className="flex flex-col gap-3">
                {[
                  {
                    label: `${agentFlowSkillSlug(draftFlow.name)}/SKILL.md`,
                    text: `---\nname: ${agentFlowSkillSlug(draftFlow.name)}\ndescription: ${buildAgentFlowSkillDescription(draftFlow)}\n---\n\n${buildAgentFlowSkillBody(draftFlow)}`,
                  },
                  {
                    label: `${agentFlowSkillSlug(draftFlow.name)}/flow.json`,
                    text: serializeAgentFlowSkillFile(draftFlow),
                  },
                ].map((file) => (
                  <div key={file.label} className="flex flex-col gap-1">
                    <span className="font-mono text-[11px] text-gray-10">
                      {file.label}
                    </span>
                    <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-gray-5 bg-gray-1 p-2.5 font-mono text-[11px] text-gray-12 leading-relaxed">
                      {file.text}
                    </pre>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-lg border border-gray-5 border-dashed p-3 text-[12px] text-gray-10">
                Finish the steps to see the generated skill files.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
