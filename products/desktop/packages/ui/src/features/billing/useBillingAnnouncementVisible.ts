import { USAGE_BILLING_FLAG } from "@posthog/shared";
import { useAuthStateValue } from "../auth/store";
import { useFeatureFlag } from "../feature-flags/useFeatureFlag";
import { useBillingAnnouncementStore } from "./billingAnnouncementStore";

/** Whether the one-time billing announcement is currently blocking the app. */
export function useBillingAnnouncementVisible(): boolean {
  const armed = useFeatureFlag(USAGE_BILLING_FLAG);
  const acknowledged = useBillingAnnouncementStore((s) => s.acknowledged);
  const hasHydrated = useBillingAnnouncementStore((s) => s._hasHydrated);
  const isLoggedIn = useAuthStateValue((state) => state.currentOrgId !== null);
  return armed && isLoggedIn && hasHydrated && !acknowledged;
}
