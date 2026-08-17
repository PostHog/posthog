import { QUICK_ASK_SHORTCUT_PRESETS } from "@posthog/shared/quick-ask-shortcuts";
import { z } from "zod";
import { getQuickAskState, setQuickAskShortcut } from "../../quick-ask";
import { publicProcedure, router } from "../trpc";

const quickAskStateSchema = z.object({
  enabled: z.boolean(),
  shortcut: z.string(),
  registered: z.boolean(),
});

const accelerators = QUICK_ASK_SHORTCUT_PRESETS.map(
  (preset) => preset.accelerator,
) as [string, ...string[]];

export const quickAskRouter = router({
  getState: publicProcedure
    .output(quickAskStateSchema)
    .query(() => getQuickAskState()),

  setShortcut: publicProcedure
    .input(z.object({ accelerator: z.enum(accelerators) }))
    .output(quickAskStateSchema)
    .mutation(({ input }) => setQuickAskShortcut(input.accelerator)),
});
