import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { useRef } from "react";

/**
 * Returns the latest config option, falling back to the last non-empty value
 * while the option is transiently absent.
 *
 * The preview config is cleared and refetched whenever the harness changes, so
 * `modeOption`/`modelOption`/`thoughtOption` momentarily read as `undefined`
 * mid-switch. Selectors that key their visibility on those values would unmount
 * and remount, collapsing the toolbar and yanking any open menu sideways.
 * Retaining the previous option lets a selector stay mounted (rendered disabled)
 * until the new harness's config lands, so the switch reads as a smooth update
 * rather than a flicker. The retained value is for display only — submission
 * keeps reading the live (cleared) option, so a stale id is never sent.
 */
export function useRetainedConfigOption(
  option: SessionConfigOption | undefined,
): SessionConfigOption | undefined {
  const lastSeen = useRef(option);
  if (option) lastSeen.current = option;
  return option ?? lastSeen.current;
}
