import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";
import type { OrgConsent } from "./useOrgConsent";

export type ConsentSurface = "onboarding_step" | "standalone_gate";

export function useConsentAnalytics(
  consent: OrgConsent,
  isAdmin: boolean,
  surface: ConsentSurface,
): void {
  const needsAiConsent =
    consent.status === "resolved" ? consent.needsAiConsent : undefined;
  const needsBetaTerms =
    consent.status === "resolved" ? consent.needsBetaTerms : undefined;
  const previousAi = useRef<boolean | undefined>(undefined);
  const previousBeta = useRef<boolean | undefined>(undefined);
  const gateTracked = useRef(false);

  useEffect(() => {
    if (
      !gateTracked.current &&
      (needsAiConsent === true || needsBetaTerms === true)
    ) {
      gateTracked.current = true;
      track(ANALYTICS_EVENTS.AI_CONSENT_GATE_SHOWN, {
        is_org_admin: isAdmin,
        outstanding_ai_consent: needsAiConsent === true,
        outstanding_beta_terms: needsBetaTerms === true,
        surface,
      });
    }
  }, [isAdmin, needsAiConsent, needsBetaTerms, surface]);

  useEffect(() => {
    if (previousAi.current === true && needsAiConsent === false) {
      track(ANALYTICS_EVENTS.AI_CONSENT_APPROVED);
    }
    if (previousBeta.current === true && needsBetaTerms === false) {
      track(ANALYTICS_EVENTS.DESKTOP_BETA_TERMS_ACCEPTED);
    }
    previousAi.current = needsAiConsent;
    previousBeta.current = needsBetaTerms;
  }, [needsAiConsent, needsBetaTerms]);
}
