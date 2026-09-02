import { isValidQuickAskAccelerator } from "@posthog/shared/quick-ask-shortcuts";
import { z } from "zod";
import {
  getQuickAskState,
  setQuickAskSettings,
  setQuickAskShortcut,
} from "../../quick-ask";
import { publicProcedure, router } from "../trpc";

const quickAskStateSchema = z.object({
  enabled: z.boolean(),
  active: z.boolean(),
  shortcut: z.string(),
  registered: z.boolean(),
  defaultChannelId: z.string(),
  defaultRepositories: z.array(z.string()),
  defaultGithubIntegrationId: z.number(),
  defaultAdapter: z.string(),
  defaultModel: z.string(),
  defaultEffort: z.string(),
});

export const quickAskRouter = router({
  getState: publicProcedure
    .output(quickAskStateSchema)
    .query(() => getQuickAskState()),

  setShortcut: publicProcedure
    .input(
      z.object({
        accelerator: z
          .string()
          .max(64)
          .refine(isValidQuickAskAccelerator, "Not a recordable shortcut"),
      }),
    )
    .output(quickAskStateSchema)
    .mutation(({ input }) => setQuickAskShortcut(input.accelerator)),

  setSettings: publicProcedure
    .input(
      z.object({
        active: z.boolean().optional(),
        defaultChannelId: z.string().optional(),
        defaultRepositories: z.array(z.string()).optional(),
        defaultGithubIntegrationId: z.number().optional(),
        defaultAdapter: z.enum(["", "claude", "codex"]).optional(),
        defaultModel: z.string().max(120).optional(),
        defaultEffort: z.string().max(32).optional(),
      }),
    )
    .output(quickAskStateSchema)
    .mutation(({ input }) => setQuickAskSettings(input)),
});
