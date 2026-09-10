import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  type ISpeechSynthesizer,
  SPEECH_SYNTHESIZER_SERVICE,
} from "@posthog/workspace-server/services/speech/identifiers";
import { z } from "zod";

export const speechRouter = router({
  // Synthesizes MP3 bytes (key stays in the host); the renderer plays them.
  // Returns null when no key is set or synthesis fails.
  synthesize: publicProcedure
    .input(
      z.object({
        text: z.string().min(1).max(2000),
        voiceId: z.string().optional(),
      }),
    )
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISpeechSynthesizer>(SPEECH_SYNTHESIZER_SERVICE)
        .synthesize(input.text, input.voiceId),
    ),
});
