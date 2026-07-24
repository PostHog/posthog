import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import {
  AuthServiceEvent,
  authStateSchema,
  loginInput,
  loginOutput,
  redeemInviteCodeInput,
  selectProjectInput,
  switchOrgInput,
  validAccessTokenOutput,
} from "@posthog/core/auth/schemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const authRouter = router({
  getState: publicProcedure.output(authStateSchema).query(({ ctx }) => {
    return ctx.container.get<AuthService>(AUTH_SERVICE).getState();
  }),

  onStateChanged: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<AuthService>(AUTH_SERVICE);
    const iterable = service.toIterable(AuthServiceEvent.StateChanged, {
      signal: opts.signal,
    });
    for await (const state of iterable) {
      yield state;
    }
  }),

  login: publicProcedure
    .input(loginInput)
    .output(loginOutput)
    .mutation(async ({ ctx, input }) => ({
      state: await ctx.container
        .get<AuthService>(AUTH_SERVICE)
        .login(input.region),
    })),

  signup: publicProcedure
    .input(loginInput)
    .output(loginOutput)
    .mutation(async ({ ctx, input }) => ({
      state: await ctx.container
        .get<AuthService>(AUTH_SERVICE)
        .signup(input.region),
    })),

  getValidAccessToken: publicProcedure
    .output(validAccessTokenOutput)
    .query(async ({ ctx }) =>
      ctx.container.get<AuthService>(AUTH_SERVICE).getValidAccessToken(),
    ),

  refreshAccessToken: publicProcedure
    .output(validAccessTokenOutput)
    .mutation(async ({ ctx }) =>
      ctx.container.get<AuthService>(AUTH_SERVICE).refreshAccessToken(),
    ),

  selectProject: publicProcedure
    .input(selectProjectInput)
    .output(authStateSchema)
    .mutation(async ({ ctx, input }) =>
      ctx.container
        .get<AuthService>(AUTH_SERVICE)
        .selectProject(input.projectId),
    ),

  switchOrg: publicProcedure
    .input(switchOrgInput)
    .output(authStateSchema)
    .mutation(async ({ ctx, input }) =>
      ctx.container.get<AuthService>(AUTH_SERVICE).switchOrg(input.orgId),
    ),

  redeemInviteCode: publicProcedure
    .input(redeemInviteCodeInput)
    .output(authStateSchema)
    .mutation(async ({ ctx, input }) =>
      ctx.container.get<AuthService>(AUTH_SERVICE).redeemInviteCode(input.code),
    ),

  logout: publicProcedure.output(authStateSchema).mutation(async ({ ctx }) => {
    return ctx.container.get<AuthService>(AUTH_SERVICE).logout();
  }),
});
