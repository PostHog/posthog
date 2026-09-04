import { avatarColor } from "@posthog/core/auth/avatarColor";
import {
  BoardPresenceTracker,
  type PresencePeer,
} from "@posthog/core/canvas-v2/boardPresence";
import type { CanvasV2Presence } from "@posthog/shared";
import { describe, expect, it } from "vitest";

const UUID = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b";

function ping(over: Partial<CanvasV2Presence> = {}): CanvasV2Presence {
  return {
    clientId: "other-window",
    cursor: null,
    viewport: null,
    selectedIds: [],
    carets: [],
    ...over,
  };
}

function track(presence: CanvasV2Presence): PresencePeer {
  let peers: PresencePeer[] = [];
  const tracker = new BoardPresenceTracker({
    localClientId: "mine",
    unknownName: "Someone",
    onChange: (next) => {
      peers = next;
    },
  });
  tracker.ingest(presence);
  return peers[0];
}

describe("BoardPresenceTracker", () => {
  it("takes the color and the initials from the person, not from the window", () => {
    const first = track(
      ping({
        clientId: "window-a",
        userId: 7,
        userUuid: UUID,
        userName: "Ada Lovelace",
        userEmail: "ada@example.com",
      }),
    );
    const second = track(
      ping({
        clientId: "window-b",
        userId: 7,
        userUuid: UUID,
        userName: "Ada Lovelace",
        userEmail: "ada@example.com",
      }),
    );

    expect(first.color).toEqual(avatarColor(UUID));
    expect(second.color).toEqual(first.color);
    expect(first.initials).toBe("AL");
    expect(first.user.email).toBe("ada@example.com");
  });

  it("falls back to the client id when the ping names nobody", () => {
    const peer = track(ping({ clientId: "window-c" }));

    expect(peer.name).toBe("Someone");
    expect(peer.color).toEqual(avatarColor("client:window-c"));
  });
});
