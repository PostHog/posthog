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
} from "@posthog/quill";
import {
  AGENT_FLOW_ROLES,
  type AgentFlowDefinition,
  type AgentFlowEffort,
  type AgentFlowRole,
  type AgentFlowStep,
} from "@posthog/shared";
import { useMemo, useState } from "react";

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

const ROLE_LABELS: Record<AgentFlowRole, string> = {
  researcher: "Research",
  planner: "Plan",
  executor: "Implement",
  reviewer: "Review",
};

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
  onSave,
  onCancel,
}: {
  models: AgentFlowModelOption[];
  flow?: AgentFlowDefinition;
  initialName: string;
  initialRoles: AgentFlowRole[];
  onSave: (flow: AgentFlowDefinition) => void;
  onCancel: () => void;
}) {
  const defaultModel = models.find((model) => model.isDefault) ?? models[0];
  const [name, setName] = useState(flow?.name ?? initialName);
  const [steps, setSteps] = useState<DraftStep[]>(() =>
    initialSteps(flow, initialRoles, defaultModel),
  );

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
        <div>
          <h2 className="font-semibold text-[18px] text-gray-12">
            {flow ? "Edit flow" : "New flow"}
          </h2>
          <Text size="xs" variant="muted">
            Steps run from top to bottom. Each step uses its exact Pi model and
            effort.
          </Text>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>

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

      <div className="flex flex-col gap-3">
        {steps.map((step, stepIndex) => {
          const selectedModel = models.find(
            (model) => model.id === step.modelId,
          );
          const effortOptions = selectedModel?.thinkingLevels ?? [];
          return (
            <div
              key={step.id}
              className="rounded-lg border border-gray-5 bg-gray-1 p-4"
            >
              <div className="mb-3 flex items-center justify-between gap-2">
                <Text size="sm" className="font-semibold text-gray-12">
                  {stepIndex + 1}. {step.name || "Step"}
                </Text>
                <div className="flex items-center gap-1">
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

              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <div className="flex flex-col gap-1.5">
                  <Text size="xs" className="font-medium text-gray-12">
                    Role
                  </Text>
                  <Select
                    value={step.role}
                    onValueChange={(value) => {
                      if (!value) return;
                      const role = value as AgentFlowRole;
                      updateStep(step.id, { role, name: ROLE_LABELS[role] });
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
                  <Text size="xs" className="font-medium text-gray-12">
                    Model
                  </Text>
                  <Select
                    value={step.modelId}
                    onValueChange={(value) => {
                      const model = models.find((item) => item.id === value);
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
                  <Text size="xs" className="font-medium text-gray-12">
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
                    <SelectTrigger size="sm" aria-label="Reasoning effort">
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

              <div className="mt-3 flex flex-col gap-1.5">
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

              {stepIndex < steps.length - 1 ? (
                <div className="mt-3 flex items-center justify-between gap-3 border-gray-5 border-t pt-3">
                  <div>
                    <Text size="xs" className="font-medium text-gray-12">
                      Ask before the next step
                    </Text>
                    <Text size="xs" variant="muted" className="block">
                      Show this step's output and wait for approval.
                    </Text>
                  </div>
                  <Switch
                    checked={step.approvalAfter}
                    aria-label={`Ask after ${step.name}`}
                    onCheckedChange={(checked) =>
                      updateStep(step.id, { approvalAfter: checked })
                    }
                  />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="flex items-center justify-between gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={steps.length >= 6}
          onClick={() =>
            setSteps((current) => [
              ...current,
              newDraftStep("executor", defaultModel),
            ])
          }
        >
          <Plus size={14} />
          Add step
        </Button>
        <Button
          type="button"
          variant="primary"
          size="sm"
          disabled={!canSave}
          data-attr="agent-flow-save"
          onClick={() => {
            if (!validSteps) return;
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
  );
}
