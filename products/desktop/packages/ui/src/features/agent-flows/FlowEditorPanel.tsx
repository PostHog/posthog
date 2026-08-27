import {
  CloudArrowUpIcon,
  FolderOpenIcon,
  TrashIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { AgentFlowRole } from "@posthog/shared";
import { toast } from "@posthog/ui/primitives/toast";
import { useState } from "react";
import { usePublishSkill } from "../skills/useTeamSkillMutations";
import { AgentFlowEditor, type AgentFlowModelOption } from "./AgentFlowEditor";
import {
  type AgentFlowRecord,
  useDeleteAgentFlow,
  useSaveAgentFlow,
} from "./useAgentFlows";

export interface FlowEditorState {
  key: string;
  flow?: AgentFlowRecord;
  name: string;
  roles: AgentFlowRole[];
}

/** The flow editor in the Skills page right sidebar, like the skill detail panel. */
export function FlowEditorPanel({
  state,
  models,
  canPublish,
  onClose,
  onOpenFiles,
}: {
  state: FlowEditorState;
  models: AgentFlowModelOption[];
  canPublish: boolean;
  onClose: () => void;
  onOpenFiles: (skillPath: string) => void;
}) {
  const { save, isSaving } = useSaveAgentFlow();
  const { deleteFlow, isDeleting } = useDeleteAgentFlow();
  const publishSkill = usePublishSkill();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const existing = state.flow;

  const handlePublish = async () => {
    if (!existing) {
      return;
    }
    try {
      const result = await publishSkill.mutateAsync({
        skillPath: existing.skillPath,
      });
      setConfirmPublish(false);
      toast.success(`Published ${existing.name} (v${result.version})`);
    } catch (error) {
      toast.error("Failed to publish the flow", {
        description: error instanceof Error ? error.message : undefined,
      });
    }
  };

  const iconAction = (
    label: string,
    icon: React.ReactNode,
    onClick: () => void,
  ) => (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            variant="link-muted"
            size="icon-sm"
            aria-label={label}
            onClick={onClick}
          >
            {icon}
          </Button>
        }
      />
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-gray-4 border-b px-3 py-2">
        <span className="truncate font-semibold text-[13px] text-gray-12">
          {existing ? existing.name : "New flow"}
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
          {existing && canPublish
            ? iconAction(
                "Publish to team",
                <CloudArrowUpIcon size={14} />,
                () => setConfirmPublish(true),
              )
            : null}
          {existing
            ? iconAction("Open files", <FolderOpenIcon size={14} />, () =>
                onOpenFiles(existing.skillPath),
              )
            : null}
          {existing
            ? iconAction("Delete flow", <TrashIcon size={14} />, () =>
                setConfirmDelete(true),
              )
            : null}
          {iconAction("Close", <XIcon size={14} />, onClose)}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <AgentFlowEditor
          key={state.key}
          compact
          models={models}
          flow={existing}
          initialName={state.name}
          initialRoles={state.roles}
          saving={isSaving}
          onCancel={onClose}
          onSave={(flow) => {
            void save({ flow, skillPath: existing?.skillPath })
              .then(onClose)
              .catch(() => {});
          }}
        />
      </div>

      <AlertDialog
        open={confirmDelete}
        onOpenChange={(open) => {
          if (!open) setConfirmDelete(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete flow?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes the "{existing?.name}" flow and its skill
              folder. Tasks that already ran with it are not affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={isDeleting}
              onClick={() => setConfirmDelete(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              loading={isDeleting}
              disabled={isDeleting}
              onClick={() => {
                if (!existing) {
                  return;
                }
                void deleteFlow(existing.skillPath)
                  .catch(() => {})
                  .finally(() => {
                    setConfirmDelete(false);
                    onClose();
                  });
              }}
            >
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={confirmPublish}
        onOpenChange={(open) => {
          if (!open) setConfirmPublish(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Publish to team?</AlertDialogTitle>
            <AlertDialogDescription>
              This shares the "{existing?.name}" flow with your team. Teammates
              can install it from the Team tab and run it in their own tasks.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={publishSkill.isPending}
              onClick={() => setConfirmPublish(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              loading={publishSkill.isPending}
              disabled={publishSkill.isPending}
              onClick={() => void handlePublish()}
            >
              Publish
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
