import type {
  CreateResourceCommentRequest,
  ResourceComment,
} from "@posthog/api-client/posthog-client";
import type { CommentTarget } from "@posthog/core/comments/anchors";
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

function taskCommentsQueryKey(
  authIdentity: string | null,
  taskId: string,
): readonly ["comments", string | null, string] {
  return ["comments", authIdentity, taskId];
}

export function commentsForTarget(
  comments: ResourceComment[],
  target: CommentTarget,
): ResourceComment[] {
  return comments.filter(
    (comment) =>
      comment.scope === target.scope && comment.item_id === target.itemId,
  );
}

export function isOptimisticComment(comment: ResourceComment): boolean {
  return comment.id.startsWith("optimistic-");
}

export function useTaskCommentsQuery<TData = ResourceComment[]>(
  taskId: string,
  options: {
    enabled?: boolean;
    refetchInterval?: number | false;
    select?: (comments: ResourceComment[]) => TData;
  } = {},
) {
  const service = useService<SessionService>(SESSION_SERVICE);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  return useQuery({
    queryKey: taskCommentsQueryKey(authIdentity, taskId),
    queryFn: () => service.getTaskComments(taskId),
    enabled: options.enabled !== false && authIdentity !== null && !!taskId,
    staleTime: 3_000,
    refetchInterval: options.refetchInterval ?? 15_000,
    refetchIntervalInBackground: false,
    select: options.select,
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
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const queryKey = taskCommentsQueryKey(authIdentity, taskId ?? "");
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
      await queryClient.cancelQueries({ queryKey, exact: true });
      const previous = queryClient.getQueryData<ResourceComment[]>(queryKey);
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
      queryClient.setQueryData<ResourceComment[]>(queryKey, (current) =>
        current ? [...current, optimistic] : current,
      );
      return { previous, optimisticId: optimistic.id };
    },
    onSuccess: (saved, _request, context) => {
      queryClient.setQueryData<ResourceComment[]>(queryKey, (current) =>
        current?.map((comment) =>
          comment.id === context.optimisticId ? saved : comment,
        ),
      );
    },
    onError: (_error, _request, context) => {
      queryClient.setQueryData(queryKey, context?.previous);
      toast.error("Couldn't save comment", {
        description: "Try again.",
      });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey, exact: true }),
  });
}

export function useSetCommentResolved(target: CommentTarget, taskId: string) {
  const service = useService<SessionService>(SESSION_SERVICE);
  const queryClient = useQueryClient();
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const queryKey = taskCommentsQueryKey(authIdentity, taskId);

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
      await queryClient.cancelQueries({ queryKey, exact: true });
      const previous = queryClient.getQueryData<ResourceComment[]>(queryKey);
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
      queryClient.setQueryData<ResourceComment[]>(queryKey, (current) =>
        current ? [...current, optimistic] : current,
      );
      return { previous };
    },
    onError: (_error, _variables, context) => {
      queryClient.setQueryData(queryKey, context?.previous);
      toast.error("Couldn't update comment", {
        description: "Try again.",
      });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey, exact: true }),
  });
}
