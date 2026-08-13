import {
  type CodeUsageMeter,
  codeUsageMeter,
  isCodeUsageFreeTier,
  isUsageExceeded,
} from "@posthog/core/billing/usageDisplay";
import { useUsage } from "./useUsage";

export interface UsageMeterState {
  meter: CodeUsageMeter;
  freeTier: boolean;
  blocked: boolean;
  // True while the meter could still appear but data hasn't arrived —
  // distinguishes "show skeleton" from "render nothing".
  isLoading: boolean;
}

export function useUsageMeter(billingEnabled: boolean): UsageMeterState {
  const { usage, isLoading } = useUsage({ enabled: billingEnabled });

  if (!billingEnabled) {
    return {
      meter: { kind: "hidden" },
      freeTier: false,
      blocked: false,
      isLoading: false,
    };
  }
  return {
    meter: codeUsageMeter(usage),
    freeTier: isCodeUsageFreeTier(usage),
    blocked: usage ? isUsageExceeded(usage) : false,
    isLoading: !usage && isLoading,
  };
}
