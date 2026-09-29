import type { GatewayModel } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { DEFAULT_MODEL, DEFAULT_REPOSITORY } from "@/config";
import { useAuth } from "@/lib/auth";
import { getClient } from "@/lib/client";
import { currentRunConfig } from "@/lib/composer";
import { useRepo } from "@/lib/repo";

const TERMINAL: ReadonlySet<string> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

export const keys = {
  tasks: ["tasks"] as const,
  task: (id: string) => ["tasks", id] as const,
  models: ["models"] as const,
  repository: ["repository"] as const,
  repositories: ["repositories"] as const,
};

export function useTasks(search = "", enabled = true) {
  const session = useAuth((s) => s.session);
  const query = useInfiniteQuery({
    queryKey: [...keys.tasks, "list", session?.userId, search],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      getClient().getTasksPage({
        basic: true,
        createdBy: session?.userId,
        search: search.trim() || undefined,
        ordering: "-last_activity_at",
        limit: 100,
        offset: pageParam,
      }),
    getNextPageParam: (page, _pages, offset) => {
      const next = offset + page.tasks.length;
      return page.tasks.length > 0 && next < page.count ? next : undefined;
    },
    enabled: !!session && enabled,
    refetchInterval: (query) => {
      const tasks = query.state.data?.pages.flatMap((page) => page.tasks);
      const anyLive = tasks?.some((task) => {
        const status = task.latest_run?.status;
        return !!status && !TERMINAL.has(status);
      });
      return anyLive ? 5000 : 30000;
    },
  });
  const tasks = query.data?.pages.flatMap((page) => page.tasks) ?? [];
  return {
    ...query,
    data: [...new Map(tasks.map((task) => [task.id, task])).values()].filter(
      (task) =>
        task.latest_run?.environment !== "local" &&
        !task.origin_key?.startsWith("desktop_onboarding"),
    ),
  };
}

export function useTask(taskId: string) {
  const session = useAuth((s) => s.session);
  return useQuery({
    queryKey: keys.task(taskId),
    queryFn: () => getClient().getTask(taskId),
    enabled: !!session && !!taskId,
    refetchInterval: (query) => {
      const status = (query.state.data as Task | undefined)?.latest_run?.status;
      return status && !TERMINAL.has(status) ? 5000 : false;
    },
  });
}

// The gateway may not be running locally, so the pill always has a default.
export function useModels() {
  const session = useAuth((s) => s.session);
  return useQuery<GatewayModel[]>({
    queryKey: keys.models,
    queryFn: async () => {
      try {
        const models = await getClient().getCloudTaskGatewayModels();
        const allowed = models.filter((model) => model.allowed);
        return allowed.length > 0 ? allowed : fallbackModels();
      } catch {
        return fallbackModels();
      }
    },
    enabled: !!session,
    staleTime: 5 * 60_000,
  });
}

function fallbackModels(): GatewayModel[] {
  return [
    {
      id: DEFAULT_MODEL,
      owned_by: "anthropic",
      context_window: 200_000,
      supports_streaming: true,
      supports_vision: true,
      allowed: true,
    },
  ];
}

// Most recently used repository on this project, else the configured default.
// The chosen repo wins, then the config default, then the most recently used.
export function useDefaultRepository() {
  const tasks = useTasks();
  const chosen = useRepo((s) => s.repository);
  const recent = tasks.data?.find((task) => task.repository)?.repository;
  return {
    data:
      chosen !== undefined ? chosen : (DEFAULT_REPOSITORY ?? recent ?? null),
    isLoading: chosen === undefined && tasks.isLoading,
  };
}

export function useRepositories() {
  const session = useAuth((s) => s.session);
  return useQuery<string[]>({
    queryKey: keys.repositories,
    queryFn: async () => {
      const client = getClient();
      const integrations = await client.getGithubUserIntegrations();
      const lists = await Promise.all(
        integrations.map((integration) =>
          client.getGithubUserRepositories(integration.installation_id),
        ),
      );
      return [...new Set(lists.flat())].sort();
    },
    enabled: !!session,
    staleTime: 5 * 60_000,
  });
}

export function useInvalidateTasks() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: keys.tasks });
}

export async function createAndRunTask(input: {
  prompt: string;
  wirePrompt?: string;
  repository: string | null;
}): Promise<Task> {
  const client = getClient();
  const task = await client.createTask({
    description: input.prompt,
    title: input.prompt.slice(0, 100),
    repository: input.repository ?? undefined,
  });
  return client.runTaskInCloud(task.id, undefined, {
    pendingUserMessage: input.wirePrompt ?? input.prompt,
    ...currentRunConfig(),
  });
}
