import type { ContextMenuService } from "@posthog/core/context-menu/context-menu";
import { CONTEXT_MENU_CONTROLLER } from "@posthog/core/context-menu/identifiers";
import {
  archivedTaskContextMenuInput,
  archivedTaskContextMenuOutput,
  bulkTaskContextMenuInput,
  bulkTaskContextMenuOutput,
  confirmDeleteArchivedTaskInput,
  confirmDeleteArchivedTaskOutput,
  confirmDeleteTaskInput,
  confirmDeleteTaskOutput,
  confirmDeleteWorktreeInput,
  confirmDeleteWorktreeOutput,
  fileContextMenuInput,
  fileContextMenuOutput,
  folderContextMenuInput,
  folderContextMenuOutput,
  splitContextMenuOutput,
  tabContextMenuInput,
  tabContextMenuOutput,
  taskContextMenuInput,
  taskContextMenuOutput,
} from "@posthog/core/context-menu/schemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const contextMenuRouter = router({
  confirmDeleteTask: publicProcedure
    .input(confirmDeleteTaskInput)
    .output(confirmDeleteTaskOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .confirmDeleteTask(input),
    ),

  confirmDeleteArchivedTask: publicProcedure
    .input(confirmDeleteArchivedTaskInput)
    .output(confirmDeleteArchivedTaskOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .confirmDeleteArchivedTask(input),
    ),

  confirmDeleteWorktree: publicProcedure
    .input(confirmDeleteWorktreeInput)
    .output(confirmDeleteWorktreeOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .confirmDeleteWorktree(input),
    ),

  showTaskContextMenu: publicProcedure
    .input(taskContextMenuInput)
    .output(taskContextMenuOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .showTaskContextMenu(input),
    ),

  showBulkTaskContextMenu: publicProcedure
    .input(bulkTaskContextMenuInput)
    .output(bulkTaskContextMenuOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .showBulkTaskContextMenu(input),
    ),

  showArchivedTaskContextMenu: publicProcedure
    .input(archivedTaskContextMenuInput)
    .output(archivedTaskContextMenuOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .showArchivedTaskContextMenu(input),
    ),

  showFolderContextMenu: publicProcedure
    .input(folderContextMenuInput)
    .output(folderContextMenuOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .showFolderContextMenu(input),
    ),

  showTabContextMenu: publicProcedure
    .input(tabContextMenuInput)
    .output(tabContextMenuOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .showTabContextMenu(input),
    ),

  showSplitContextMenu: publicProcedure
    .output(splitContextMenuOutput)
    .mutation(({ ctx }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .showSplitContextMenu(),
    ),

  showFileContextMenu: publicProcedure
    .input(fileContextMenuInput)
    .output(fileContextMenuOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ContextMenuService>(CONTEXT_MENU_CONTROLLER)
        .showFileContextMenu(input),
    ),
});
