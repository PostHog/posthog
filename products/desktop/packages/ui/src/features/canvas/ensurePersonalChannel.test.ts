import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { describe, expect, it } from "vitest";
import { ensurePersonalChannel } from "./ensurePersonalChannel";

function channel(over: Partial<Channel> = {}): Channel {
  return {
    id: "c1",
    name: "growth",
    channelType: "public",
    starred: false,
    ...over,
  };
}

describe("ensurePersonalChannel", () => {
  it("finds the personal channel among shared ones", () => {
    const me = channel({ id: "me-id", name: "me", channelType: "personal" });
    expect(ensurePersonalChannel([channel(), me])).toBe(me);
  });

  it("selects by channel type, not name", () => {
    // A shared channel someone named "me" must not pass for the private one.
    const impostor = channel({ id: "c2", name: "me" });
    expect(ensurePersonalChannel([impostor])).toBeUndefined();
  });

  it("returns undefined until the list has loaded (or provisioned) it", () => {
    expect(ensurePersonalChannel([])).toBeUndefined();
  });
});
