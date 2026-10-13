import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import type { PiQueueSnapshot } from "./types";

export const POSTHOG_PI_QUEUE_ENTRY_TYPE = "posthog.pi.queue";

export function readPersistedPiQueue(entries: SessionEntry[]): PiQueueSnapshot {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (
      entry?.type !== "custom" ||
      entry.customType !== POSTHOG_PI_QUEUE_ENTRY_TYPE
    ) {
      continue;
    }
    const data = entry.data as Partial<PiQueueSnapshot> | undefined;
    if (
      Array.isArray(data?.steering) &&
      data.steering.every((message) => typeof message === "string") &&
      Array.isArray(data.followUp) &&
      data.followUp.every((message) => typeof message === "string")
    ) {
      return {
        steering: [...data.steering],
        followUp: [...data.followUp],
      };
    }
  }

  return { steering: [], followUp: [] };
}
