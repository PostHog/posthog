import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  ONBOARDING_IMPORT_SERVICE,
  type OnboardingImportService,
} from "@posthog/workspace-server/services/onboarding-import/identifiers";
import { summaryOutput } from "@posthog/workspace-server/services/onboarding-import/schemas";

export const onboardingImportRouter = router({
  getSummary: publicProcedure
    .output(summaryOutput)
    .query(({ ctx }) =>
      ctx.container
        .get<OnboardingImportService>(ONBOARDING_IMPORT_SERVICE)
        .getSummary(),
    ),
});
