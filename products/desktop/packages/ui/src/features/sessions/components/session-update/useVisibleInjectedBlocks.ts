import type { InjectedBlock } from "@posthog/core/editor/injectedBlocks";
import { visibleInjectedBlocks } from "@posthog/ui/features/sessions/components/session-update/injectedBlocks";
import { useMemo } from "react";

export function useVisibleInjectedBlocks(
  blocks: InjectedBlock[],
): InjectedBlock[] {
  return useMemo(() => visibleInjectedBlocks(blocks), [blocks]);
}
