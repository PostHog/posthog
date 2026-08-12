import type {
  CreateResourceCommentRequest,
  ResourceComment,
} from "@posthog/api-client/posthog-client";
import {
  type CommentTarget,
  commentTargetKey,
} from "@posthog/core/comments/anchors";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { toast } from "@posthog/ui/primitives/toast";
import {
  type QueryClient,
  type QueryKey,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

function commentsQueryKey(
  authIdentity: string | null,
  target: CommentTarget | null,
  taskId: string,
) {
  return [
    "comments",
    authIdentity,
    taskId,
    target?.scope ?? "",
    target?.itemId ?? "",
  ] as const;
}

/**
 * Whether a cached comment list contains the target's comments — true for the
 * target's own single-resource query and for any fan-out query whose set
 * includes it. Both key shapes spell the target out, so this needs no cache
 * contents. Matching per target rather than on the `["comments"]` prefix keeps
 * an optimistic write out of other resources' caches.
 */
export function commentCacheCoversTarget(
  queryKey: readonly unknown[],
  target: CommentTarget,
): boolean {
  if (queryKey[0] !== "comments") return false;
  if (queryKey[1] === "targets") {
    return String(queryKey[4] ?? "")
      .split(",")
      .includes(commentTargetKey(target));
  }
  return queryKey[3] === target.scope && queryKey[4] === target.itemId;
}

/** Filter for every cached comment list an optimistic write has to patch. */
function commentCachesCoveringTarget(target: CommentTarget) {
  return {
    queryKey: ["comments"] as const,
    predicate: (query: { queryKey: readonly unknown[] }) =>
      commentCacheCoversTarget(query.queryKey, target),
  };
}

type CommentCacheFilter = ReturnType<typeof commentCachesCoveringTarget>;
type CommentCacheSnapshot = [QueryKey, ResourceComment[] | undefined][];

/** Only patches lists that have already loaded: appending to a pending query
 *  would fabricate a result its own fetch is about to replace. */
function appendOptimisticComment(
  queryClient: QueryClient,
  caches: CommentCacheFilter,
  optimistic: ResourceComment,
) {
  queryClient.setQueriesData<ResourceComment[]>(caches, (current) =>
    current ? [...current, optimistic] : current,
  );
}

function restoreCommentCaches(
  queryClient: QueryClient,
  snapshot: CommentCacheSnapshot | undefined,
) {
  for (const [queryKey, comments] of snapshot ?? []) {
    queryClient.setQueryData(queryKey, comments);
  }
}

function replaceOptimisticComment(
  queryClient: QueryClient,
  caches: CommentCacheFilter,
  optimisticId: string,
  saved: ResourceComment,
) {
  queryClient.setQueriesData<ResourceComment[]>(caches, (current) =>
    current?.map((comment) => (comment.id === optimisticId ? saved : comment)),
  );
}

export function isOptimisticComment(comment: ResourceComment): boolean {
  return comment.id.startsWith("optimistic-");
}

export function useCommentsQuery(
  target: CommentTarget | null,
  taskId: string,
  options: { enabled?: boolean; live?: boolean } = {},
) {
  const service = useService<SessionService>(SESSION_SERVICE);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  return useQuery({
    queryKey: commentsQueryKey(authIdentity, target, taskId),
    queryFn: () =>
      target
        ? service.getResourceComments(target, taskId)
        : Promise.resolve([]),
    enabled: options.enabled !== false && authIdentity !== null && !!target,
    staleTime: 3_000,
    refetchInterval: options.live === false ? false : 5_000,
    refetchIntervalInBackground: false,
    meta: AUTH_SCOPED_QUERY_META,
  });
}

/**
 * One query for every comment across a set of resources. The service does the
 * fan-out, so this stays a single-query hook and the pane makes one request
 * instead of one per row. `live: false` by default — a list of N resources must
 * never turn into N polling loops, and `intervalMs` lets a live caller pick a
 * cadence that accounts for the fan-out rather than inheriting a per-row one.
 */
export function useCommentsForTargetsQuery(
  targets: CommentTarget[],
  taskId: string,
  options: { enabled?: boolean; live?: boolean; intervalMs?: number } = {},
) {
  const service = useService<SessionService>(SESSION_SERVICE);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  // Sorted so key identity tracks the set, not row order.
  const key = targets.map(commentTargetKey).sort().join(",");
  return useQuery({
    queryKey: ["comments", "targets", authIdentity, taskId, key] as const,
    queryFn: () => service.getResourceCommentsForTargets(targets, taskId),
    enabled:
      options.enabled !== false && authIdentity !== null && targets.length > 0,
    staleTime: 3_000,
    refetchInterval: options.live ? (options.intervalMs ?? 5_000) : false,
    refetchIntervalInBackground: false,
    meta: AUTH_SCOPED_QUERY_META,
  });
}

/**
 * @param taskId Names the task the resource belongs to, so a mention on it reaches that
 * task's activity feed — the server can't resolve an artifact or canvas id back to a task.
 */
export function useCreateComment(target: CommentTarget, taskId?: string) {
  const service = useService<SessionService>(SESSION_SERVICE);
  const queryClient = useQueryClient();
  const caches = commentCachesCoveringTarget(target);
  const contextWithTask = (context: unknown) =>
    taskId ? { ...(context as Record<string, unknown>), taskId } : context;

  return useMutation({
    mutationFn: (
      request: Omit<CreateResourceCommentRequest, "scope" | "itemId">,
    ) =>
      service.createResourceComment({
        ...request,
        ...target,
        context: contextWithTask(request.context),
      }),
    onMutate: async (request) => {
      await queryClient.cancelQueries(caches);
      const previous = queryClient.getQueriesData<ResourceComment[]>(caches);
      const optimistic: ResourceComment = {
        id: `optimistic-${crypto.randomUUID()}`,
        created_by: null,
        content: request.content,
        created_at: new Date().toISOString(),
        item_id: target.itemId,
        item_context: contextWithTask(request.context),
        scope: target.scope,
        source_comment: request.sourceCommentId ?? null,
        completed_at: null,
      };
      appendOptimisticComment(queryClient, caches, optimistic);
      return { previous, optimisticId: optimistic.id };
    },
    onSuccess: (saved, _request, context) => {
      replaceOptimisticComment(
        queryClient,
        caches,
        context.optimisticId,
        saved,
      );
    },
    onError: (_error, _request, context) => {
      restoreCommentCaches(queryClient, context?.previous);
      toast.error("Couldn't save comment", {
        description: "Try again.",
      });
    },
    onSettled: () => queryClient.invalidateQueries(caches),
  });
}

export function useSetCommentResolved(target: CommentTarget) {
  const service = useService<SessionService>(SESSION_SERVICE);
  const queryClient = useQueryClient();
  const caches = commentCachesCoveringTarget(target);

  return useMutation({
    mutationFn: ({
      root,
      resolved,
    }: {
      root: ResourceComment;
      resolved: boolean;
    }) => {
      const rootContext =
        root.item_context && typeof root.item_context === "object"
          ? root.item_context
          : {};
      return service.createResourceComment({
        ...target,
        content: resolved ? "Resolved this thread" : "Reopened this thread",
        sourceCommentId: root.id,
        context: {
          ...rootContext,
          threadState: resolved ? "resolved" : "open",
        },
      });
    },
    onMutate: async ({ root, resolved }) => {
      await queryClient.cancelQueries(caches);
      const previous = queryClient.getQueriesData<ResourceComment[]>(caches);
      const rootContext =
        root.item_context && typeof root.item_context === "object"
          ? root.item_context
          : {};
      const optimistic: ResourceComment = {
        id: `optimistic-state-${crypto.randomUUID()}`,
        created_by: null,
        content: resolved ? "Resolved this thread" : "Reopened this thread",
        created_at: new Date().toISOString(),
        item_id: target.itemId,
        item_context: {
          ...rootContext,
          threadState: resolved ? "resolved" : "open",
        },
        scope: target.scope,
        source_comment: root.id,
        completed_at: null,
      };
      appendOptimisticComment(queryClient, caches, optimistic);
      return { previous };
    },
    onError: (_error, _variables, context) => {
      restoreCommentCaches(queryClient, context?.previous);
      toast.error("Couldn't update comment", {
        description: "Try again.",
      });
    },
    onSettled: () => queryClient.invalidateQueries(caches),
  });
}
