import { useHostTRPC } from "@posthog/host-router/react";
import {
  AGENT_FLOW_SKILL_FILE,
  type AgentFlowDefinition,
  agentFlowSkillSlug,
  buildAgentFlowSkillBody,
  buildAgentFlowSkillDescription,
  parseAgentFlowSkillFile,
  serializeAgentFlowSkillFile,
} from "@posthog/shared";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface AgentFlowRecord extends AgentFlowDefinition {
  skillPath: string;
}

export function useAgentFlows(): {
  flows: AgentFlowRecord[];
  isPending: boolean;
  isError: boolean;
  refetch: () => void;
} {
  const trpc = useHostTRPC();
  const list = useQuery(trpc.skills.list.queryOptions());
  const candidates = (list.data ?? []).filter(
    (skill) => skill.source === "user" && skill.editable,
  );
  const fileQueries = useQueries({
    queries: candidates.map((skill) =>
      trpc.skills.readFile.queryOptions({
        skillPath: skill.path,
        filePath: AGENT_FLOW_SKILL_FILE,
      }),
    ),
  });

  const flows: AgentFlowRecord[] = [];
  fileQueries.forEach((query, index) => {
    if (!query.data) {
      return;
    }
    const flow = parseAgentFlowSkillFile(query.data);
    if (flow) {
      flows.push({ ...flow, skillPath: candidates[index].path });
    }
  });

  return {
    flows,
    isPending: list.isPending || fileQueries.some((query) => query.isPending),
    isError: list.isError,
    refetch: () => void list.refetch(),
  };
}

function skillDirName(skillPath: string): string {
  return skillPath.split(/[\\/]/).filter(Boolean).at(-1) ?? "flow";
}

export function useSaveAgentFlow(): {
  save: (input: {
    flow: AgentFlowDefinition;
    skillPath?: string;
  }) => Promise<void>;
  isSaving: boolean;
} {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const create = useMutation(trpc.skills.create.mutationOptions());
  const saveManifest = useMutation(trpc.skills.saveManifest.mutationOptions());
  const saveFile = useMutation(trpc.skills.saveFile.mutationOptions());

  const save = async ({
    flow,
    skillPath,
  }: {
    flow: AgentFlowDefinition;
    skillPath?: string;
  }) => {
    let path = skillPath;
    if (!path) {
      const slug = agentFlowSkillSlug(flow.name);
      try {
        path = (await create.mutateAsync({ scope: "user", name: slug })).path;
      } catch {
        path = (
          await create.mutateAsync({
            scope: "user",
            name: `${slug}-${flow.id.slice(0, 8)}`,
          })
        ).path;
      }
    }
    await saveManifest.mutateAsync({
      skillPath: path,
      name: skillDirName(path),
      description: buildAgentFlowSkillDescription(flow),
      body: buildAgentFlowSkillBody(flow),
    });
    await saveFile.mutateAsync({
      skillPath: path,
      filePath: AGENT_FLOW_SKILL_FILE,
      content: serializeAgentFlowSkillFile(flow),
    });
    await queryClient.invalidateQueries(trpc.skills.pathFilter());
  };

  return {
    save,
    isSaving: create.isPending || saveManifest.isPending || saveFile.isPending,
  };
}

export function useDeleteAgentFlow(): {
  deleteFlow: (skillPath: string) => Promise<void>;
  isDeleting: boolean;
} {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const remove = useMutation(trpc.skills.delete.mutationOptions());

  return {
    deleteFlow: async (skillPath: string) => {
      await remove.mutateAsync({ skillPath });
      await queryClient.invalidateQueries(trpc.skills.pathFilter());
    },
    isDeleting: remove.isPending,
  };
}
