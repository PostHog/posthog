import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import type { ReactNode } from "react";
import { ReportsInboxView } from "../ReportsInboxView";
import { RelevancePilotContent } from "./RelevancePilotContent";

export function RelevancePilot({ children }: { children: ReactNode }) {
  const identity = useAuthStateValue(getAuthIdentity);
  const enabled = useFeatureFlag("signals-relevance-pilot", false);
  return enabled ? (
    <RelevancePilotContent key={identity}>
      <ReportsInboxView />
    </RelevancePilotContent>
  ) : (
    children
  );
}
