import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  createEnvironmentInput,
  deleteEnvironmentInput,
  environmentSchema,
  getEnvironmentInput,
  listEnvironmentsInput,
  updateEnvironmentInput,
} from "@posthog/workspace-server/services/environment/schemas";
import {
  ENVIRONMENT_CLIENT,
  type HostEnvironmentClient,
} from "../ports/environment-client";

const ws = (container: ServiceResolver) =>
  container.get<HostEnvironmentClient>(ENVIRONMENT_CLIENT);

export const environmentRouter = router({
  list: publicProcedure
    .input(listEnvironmentsInput)
    .output(environmentSchema.array())
    .query(({ ctx, input }) => ws(ctx.container).environment.list.query(input)),

  get: publicProcedure
    .input(getEnvironmentInput)
    .output(environmentSchema.nullable())
    .query(({ ctx, input }) => ws(ctx.container).environment.get.query(input)),

  create: publicProcedure
    .input(createEnvironmentInput)
    .output(environmentSchema)
    .mutation(({ ctx, input }) =>
      ws(ctx.container).environment.create.mutate(input),
    ),

  update: publicProcedure
    .input(updateEnvironmentInput)
    .output(environmentSchema)
    .mutation(({ ctx, input }) =>
      ws(ctx.container).environment.update.mutate(input),
    ),

  delete: publicProcedure
    .input(deleteEnvironmentInput)
    .mutation(({ ctx, input }) =>
      ws(ctx.container).environment.delete.mutate(input),
    ),
});
