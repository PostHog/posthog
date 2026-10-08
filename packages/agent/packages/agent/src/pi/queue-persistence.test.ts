import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";
import {
  POSTHOG_PI_QUEUE_ENTRY_TYPE,
  readPersistedPiQueue,
} from "./queue-persistence";

describe("readPersistedPiQueue", () => {
  it("uses the latest valid persisted queue snapshot", () => {
    const entries = [
      {
        type: "custom",
        customType: POSTHOG_PI_QUEUE_ENTRY_TYPE,
        data: { steering: ["old"], followUp: [] },
      },
      {
        type: "custom",
        customType: POSTHOG_PI_QUEUE_ENTRY_TYPE,
        data: { steering: ["new"], followUp: ["later"] },
      },
    ] as SessionEntry[];

    expect(readPersistedPiQueue(entries)).toEqual({
      steering: ["new"],
      followUp: ["later"],
    });
  });

  it("ignores malformed and unrelated custom entries", () => {
    const entries = [
      {
        type: "custom",
        customType: POSTHOG_PI_QUEUE_ENTRY_TYPE,
        data: { steering: [1], followUp: [] },
      },
      {
        type: "custom",
        customType: "other",
        data: { steering: ["other"], followUp: [] },
      },
    ] as SessionEntry[];

    expect(readPersistedPiQueue(entries)).toEqual({
      steering: [],
      followUp: [],
    });
  });
});
