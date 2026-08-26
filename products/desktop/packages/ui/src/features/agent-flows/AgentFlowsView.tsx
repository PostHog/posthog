import {
  FlowArrowIcon,
  PencilSimpleIcon,
  PlusIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Badge,
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Text,
} from "@posthog/quill";
import type { AgentFlowDefinition, AgentFlowRole } from "@posthog/shared";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { useState } from "react";
import { usePiModelCatalog } from "../pi-sessions/usePiModelCatalog";
import { AgentFlowEditor, type AgentFlowModelOption } from "./AgentFlowEditor";
import { type AgentFlowRecord, useAgentFlowStore } from "./agentFlowStore";

interface EditorState {
  key: string;
  flow?: AgentFlowDefinition;
  name: string;
  roles: AgentFlowRole[];
}

const PRESETS: Array<{
  name: string;
  description: string;
  roles: AgentFlowRole[];
}> = [
  {
    name: "Planner and executor",
    description: "Create a plan, approve it, and then implement it.",
    roles: ["planner", "executor"],
  },
  {
    name: "Research, plan, and execute",
    description: "Research the code, make a plan, and then implement it.",
    roles: ["researcher", "planner", "executor"],
  },
  {
    name: "Plan, execute, and review",
    description: "Make a plan, implement it, and review the result.",
    roles: ["planner", "executor", "reviewer"],
  },
];

function FlowStepChain({ flow }: { flow: AgentFlowDefinition }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {flow.steps.map((step, stepIndex) => (
        <div key={step.id} className="flex items-center gap-1.5">
          {stepIndex > 0 ? (
            <span className="text-[11px] text-gray-8">→</span>
          ) : null}
          <span className="rounded-md border border-gray-4 bg-gray-2 px-1.5 py-0.5 text-[11px] text-gray-11">
            {step.name}
            <span className="text-gray-9"> · {step.model.name}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function SavedFlowRow({
  flow,
  onEdit,
  onDelete,
}: {
  flow: AgentFlowRecord;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-gray-5 bg-gray-1 p-3 transition-colors hover:bg-gray-2">
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <Text size="sm" className="truncate font-semibold text-gray-12">
            {flow.name}
          </Text>
          <Badge variant="default">{flow.steps.length} steps</Badge>
        </div>
        <FlowStepChain flow={flow} />
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button
          type="button"
          variant="link-muted"
          size="icon-sm"
          aria-label={`Edit ${flow.name}`}
          onClick={onEdit}
        >
          <PencilSimpleIcon size={14} />
        </Button>
        <Button
          type="button"
          variant="link-muted"
          size="icon-sm"
          aria-label={`Delete ${flow.name}`}
          onClick={onDelete}
        >
          <TrashIcon size={14} />
        </Button>
      </div>
    </div>
  );
}

export function AgentFlowsView() {
  const identity = useAuthStateValue(getAuthIdentity);
  const storedFlows = useAgentFlowStore((state) => state.flows);
  const hydrated = useAgentFlowStore((state) => state._hasHydrated);
  const saveFlow = useAgentFlowStore((state) => state.saveFlow);
  const deleteFlow = useAgentFlowStore((state) => state.deleteFlow);
  const modelQuery = usePiModelCatalog(true);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AgentFlowRecord | null>(
    null,
  );
  useSetHeaderContent(null);

  const flows = identity
    ? storedFlows.filter((flow) => flow.identity === identity)
    : [];
  const models = (modelQuery.data ?? []) as AgentFlowModelOption[];
  const editingDisabledReason = !identity
    ? "Sign in to create flows."
    : models.length === 0
      ? "Pi models are still loading."
      : undefined;

  const body =
    editor && identity ? (
      <AgentFlowEditor
        key={editor.key}
        models={models}
        flow={editor.flow}
        initialName={editor.name}
        initialRoles={editor.roles}
        onCancel={() => setEditor(null)}
        onSave={(flow) => {
          saveFlow(identity, flow);
          setEditor(null);
        }}
      />
    ) : (
      <div className="flex flex-col gap-6">
        <section className="flex flex-col gap-2">
          <Text size="xs" className="font-semibold text-gray-12">
            Start with a preset
          </Text>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            {PRESETS.map((preset) => (
              <button
                key={preset.name}
                type="button"
                disabled={!!editingDisabledReason}
                className="flex min-h-24 flex-col items-start gap-1 rounded-lg border border-gray-5 bg-gray-1 p-3 text-left transition-colors hover:bg-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() =>
                  setEditor({
                    key: crypto.randomUUID(),
                    name: preset.name,
                    roles: preset.roles,
                  })
                }
              >
                <Text size="sm" className="font-semibold text-gray-12">
                  {preset.name}
                </Text>
                <Text size="xs" variant="muted">
                  {preset.description}
                </Text>
              </button>
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <Text size="xs" className="font-semibold text-gray-12">
            Saved flows
          </Text>
          {!hydrated || modelQuery.isPending ? (
            <div className="flex items-center gap-2 rounded-lg border border-gray-5 p-4 text-gray-10 text-sm">
              <Spinner />
              Loading flows...
            </div>
          ) : modelQuery.isError ? (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-red-6 bg-red-2 p-4">
              <Text size="sm">Could not load Pi models.</Text>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void modelQuery.refetch()}
              >
                Try again
              </Button>
            </div>
          ) : flows.length === 0 ? (
            <Empty className="rounded-lg border border-gray-5 border-dashed py-10">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FlowArrowIcon size={22} />
                </EmptyMedia>
                <EmptyTitle>No saved flows</EmptyTitle>
                <EmptyDescription>
                  Select a preset or create a custom flow. Saved flows appear in
                  the task composer when you start a Pi task.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="flex flex-col gap-2">
              {flows.map((flow) => (
                <SavedFlowRow
                  key={flow.id}
                  flow={flow}
                  onEdit={() =>
                    setEditor({
                      key: crypto.randomUUID(),
                      flow,
                      name: flow.name,
                      roles: flow.steps.map((step) => step.role),
                    })
                  }
                  onDelete={() => setDeleteTarget(flow)}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Flows</PageHeaderTitle>
            <PageHeaderActions>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!!editingDisabledReason || !!editor}
                onClick={() =>
                  setEditor({
                    key: crypto.randomUUID(),
                    name: "Custom flow",
                    roles: ["planner", "executor"],
                  })
                }
              >
                <PlusIcon size={14} />
                New flow
              </Button>
            </PageHeaderActions>
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            Run a task as a sequence of Pi agents. Each step has its own role,
            model, and effort, and hands its result to the next step.
          </PageHeaderDescription>
        </PageHeaderHeading>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-5xl px-8 py-8">{body}</div>
      </div>

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete flow?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes "{deleteTarget?.name}". Tasks that
              already ran with it are not affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteTarget(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                if (identity && deleteTarget) {
                  deleteFlow(identity, deleteTarget.id);
                }
                setDeleteTarget(null);
              }}
            >
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
