import type { InjectedBlock } from "@posthog/core/editor/injectedBlocks";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { visibleInjectedBlocks } from "@posthog/ui/features/sessions/components/session-update/injectedBlocks";
import { useMemo } from "react";

export function useVisibleInjectedBlocks(
  blocks: InjectedBlock[],
): InjectedBlock[] {
  const canOpenTabs = useBluebirdFlag();
  return useMemo(
    () => visibleInjectedBlocks(blocks, canOpenTabs),
    [blocks, canOpenTabs],
  );
}
