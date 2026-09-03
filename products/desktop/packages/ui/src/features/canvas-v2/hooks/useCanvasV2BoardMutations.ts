import { useHostTRPC } from "@posthog/host-router/react";
import type { CanvasV2Board } from "@posthog/shared";
import { useMutation, useQueryClient } from "@tanstack/react-query";

/** Create, rename and delete a board. Each one refreshes the board list. */
export function useCanvasV2BoardMutations(): {
  createBoard: (name: string) => Promise<CanvasV2Board>;
  renameBoard: (id: string, name: string) => Promise<CanvasV2Board>;
  removeBoard: (id: string) => Promise<void>;
  isCreating: boolean;
  isRenaming: boolean;
  isRemoving: boolean;
} {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  const invalidate = () => {
    void queryClient.invalidateQueries(trpc.canvasV2.list.pathFilter());
  };

  const create = useMutation(
    trpc.canvasV2.create.mutationOptions({ onSuccess: invalidate }),
  );
  const rename = useMutation(
    trpc.canvasV2.rename.mutationOptions({ onSuccess: invalidate }),
  );
  const remove = useMutation(
    trpc.canvasV2.remove.mutationOptions({ onSuccess: invalidate }),
  );

  return {
    createBoard: (name: string) => create.mutateAsync({ name }),
    renameBoard: (id: string, name: string) => rename.mutateAsync({ id, name }),
    removeBoard: async (id: string) => {
      await remove.mutateAsync({ id });
    },
    isCreating: create.isPending,
    isRenaming: rename.isPending,
    isRemoving: remove.isPending,
  };
}
