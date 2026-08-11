import {
  createLoop,
  destroyLoop,
  type LoopSchemas,
  partialUpdateLoop,
  runLoop,
} from "@posthog/api-client/loops";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";

export function useCreateLoop() {
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<LoopSchemas.Loop, Error, LoopSchemas.LoopWrite>({
    mutationFn: async (body) => {
      if (!loopsClient) throw new Error("Not authenticated");
      return await createLoop(loopsClient.client, loopsClient.projectId, body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.list(loopsClient?.projectId ?? null),
      });
    },
  });
}

export function useUpdateLoop(loopId: string) {
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<LoopSchemas.Loop, Error, LoopSchemas.PatchedLoop>({
    mutationFn: async (body) => {
      if (!loopsClient) throw new Error("Not authenticated");
      return await partialUpdateLoop(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
        body,
      );
    },
    onSuccess: (loop) => {
      queryClient.setQueryData(
        loopsKeys.detail(loopsClient?.projectId ?? null, loopId),
        loop,
      );
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.list(loopsClient?.projectId ?? null),
      });
    },
  });
}

export function useDeleteLoop() {
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<void, Error, string>({
    mutationFn: async (loopId) => {
      if (!loopsClient) throw new Error("Not authenticated");
      await destroyLoop(loopsClient.client, loopsClient.projectId, loopId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.list(loopsClient?.projectId ?? null),
      });
    },
  });
}

export function useRunLoop(loopId: string) {
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<LoopSchemas.LoopFireRun, Error, void>({
    mutationFn: async () => {
      if (!loopsClient) throw new Error("Not authenticated");
      return await runLoop(loopsClient.client, loopsClient.projectId, loopId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.runs(loopsClient?.projectId ?? null, loopId),
      });
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.detail(loopsClient?.projectId ?? null, loopId),
      });
    },
  });
}
