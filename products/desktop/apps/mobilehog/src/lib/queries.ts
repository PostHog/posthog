import type { GatewayModel } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { DEFAULT_MODEL, DEFAULT_REPOSITORY } from "@/config";
import { type Photo, uploadStagedPhotos } from "@/lib/attachments";
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

const PAGE_SIZE = 50;

function visibleTasks(tasks: Task[]): Task[] {
  return tasks.filter(
    (task) =>
      !task.internal &&
      task.latest_run?.environment !== "local" &&
      !task.origin_key?.startsWith("desktop_onboarding"),
  );
}

// The full task history, newest activity first, one page at a time.
export function useTaskPages(search: string, archived: boolean) {
  const session = useAuth((s) => s.session);
  const scope = archived ? "archived" : "active";
  return useInfiniteQuery({
    queryKey: search
      ? [
          ...keys.tasks,
          "created-by",
          session?.userId,
          "pages",
          scope,
          "search",
          search,
        ]
      : [...keys.tasks, "created-by", session?.userId, "pages", scope],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const page = await getClient().getTasksPage({
        basic: true,
        archived,
        createdBy: session?.userId,
        search: search || undefined,
        ordering: "-last_activity_at",
        limit: PAGE_SIZE,
        offset: pageParam,
      });
      return { ...page, visible: visibleTasks(page.tasks) };
    },
    getNextPageParam: (page, _pages, offset) => {
      const next = offset + page.tasks.length;
      return page.tasks.length > 0 && next < page.count ? next : undefined;
    },
    enabled: !!session,
  });
}

export function useTasks(search = "") {
  const session = useAuth((s) => s.session);
  return useQuery({
    queryKey: search
      ? [...keys.tasks, "created-by", session?.userId, "search", search]
      : [...keys.tasks, "created-by", session?.userId],
    queryFn: async () =>
      visibleTasks(
        await getClient().getTasks({
          basic: true,
          createdBy: session?.userId,
          search: search || undefined,
        }),
      ),
    enabled: !!session,
    refetchInterval: (query) => {
      const tasks = query.state.data as Task[] | undefined;
      const anyLive = tasks?.some((task) => {
        const status = task.latest_run?.status;
        return !!status && !TERMINAL.has(status);
      });
      return anyLive ? 5000 : 30000;
    },
  });
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

export function useUpdateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...patch
    }: {
      id: string;
      title?: string;
      archived?: boolean;
    }) => getClient().updateTask(id, patch),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.tasks }),
  });
}

export function useInvalidateTasks() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: keys.tasks });
}

export async function createAndRunTask(input: {
  prompt: string;
  repository: string | null;
  photos?: Photo[];
}): Promise<Task> {
  const client = getClient();
  const task = await client.createTask({
    description: input.prompt,
    title: input.prompt.slice(0, 100),
    repository: input.repository ?? undefined,
  });
  const artifactIds = await uploadStagedPhotos(task.id, input.photos ?? []);
  return client.runTaskInCloud(task.id, undefined, {
    pendingUserMessage: input.prompt,
    pendingUserArtifactIds: artifactIds.length ? artifactIds : undefined,
    ...currentRunConfig(),
  });
}
