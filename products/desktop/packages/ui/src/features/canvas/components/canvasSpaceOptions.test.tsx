import { LockSimpleIcon } from "@phosphor-icons/react";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { buildCanvasSpaceOptions } from "./canvasSpaceOptions";

const CHANNELS: Channel[] = [
  {
    id: "access-control",
    name: "access-control",
    channelType: "public",
    starred: false,
    repositories: [],
    createdBy: null,
  },
  {
    id: "personal",
    name: "me",
    channelType: "personal",
    starred: false,
    repositories: [],
    createdBy: null,
  },
];

describe("buildCanvasSpaceOptions", () => {
  it("puts personal above the default and uses space labels", () => {
    const options = buildCanvasSpaceOptions(CHANNELS);

    expect(options.map(({ label }) => label)).toEqual([
      "personal",
      "Every space",
      "access-control",
    ]);
    expect((options[0].icon as ReactElement).type).toBe(LockSimpleIcon);
    expect(options[2].icon).toBeNull();
  });
});
