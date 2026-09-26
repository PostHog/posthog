import { CURRENT_OWNERSHIP_FLAG } from "@posthog/core/inbox/routing";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { InboxRoutingPreferencesContent } from "./InboxRoutingPreferencesContent";

export function InboxRoutingPreferences() {
  const enabled = useFeatureFlag(CURRENT_OWNERSHIP_FLAG);
  return enabled ? <InboxRoutingPreferencesContent /> : null;
}
