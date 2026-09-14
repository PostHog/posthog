import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OrgConsent } from "./useOrgConsent";

vi.mock("@posthog/ui/shell/analytics", () => ({
  track: vi.fn(),
}));

import { track } from "@posthog/ui/shell/analytics";
import { useConsentAnalytics } from "./consentAnalytics";

const blockedConsent: OrgConsent = {
  status: "resolved",
  organizationId: "org-id",
  needsAiConsent: false,
  needsBetaTerms: true,
  satisfied: false,
  retry: vi.fn(),
};

describe("useConsentAnalytics", () => {
  beforeEach(() => {
    vi.mocked(track).mockClear();
  });

  it.each([true, false])(
    "tracks each standalone gate once when isAdmin is %s",
    async (isAdmin) => {
      const { rerender } = renderHook(
        ({ consent }: { consent: OrgConsent }) =>
          useConsentAnalytics(consent, isAdmin, "standalone_gate"),
        { initialProps: { consent: blockedConsent } },
      );

      await waitFor(() => expect(track).toHaveBeenCalledTimes(1));
      expect(track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.AI_CONSENT_GATE_SHOWN,
        {
          is_org_admin: isAdmin,
          outstanding_ai_consent: false,
          outstanding_beta_terms: true,
          surface: "standalone_gate",
        },
      );

      rerender({ consent: { ...blockedConsent } });
      expect(track).toHaveBeenCalledTimes(1);
    },
  );
});
