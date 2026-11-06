import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { beforeEach, describe, expect, it } from "vitest";
import { applyTabViewState, useChannelPaneStore } from "./channelPaneStore";

describe("applyTabViewState", () => {
  beforeEach(() => {
    useCurrentChannelStore.setState({
      currentChannelId: "space-from-prev-tab",
    });
    useChannelPaneStore.setState({
      pane: "channel",
      animateTransition: true,
    });
  });

  it.each([
    ["null clears the scoped channel", null, null],
    ["a string scopes to that space", "space-b", "space-b"],
    [
      "undefined leaves the scoped channel untouched",
      undefined,
      "space-from-prev-tab",
    ],
  ] as const)("restores spaceId: %s", (_name, spaceId, expected) => {
    applyTabViewState({ spaceId });

    expect(useCurrentChannelStore.getState().currentChannelId).toBe(expected);
    expect(useChannelPaneStore.getState().animateTransition).toBe(false);
  });

  it.each([
    ["list", true, "list"],
    ["channel", false, "channel"],
  ] as const)(
    "restores the %s pane without animating",
    (_name, listOpen, expectedPane) => {
      applyTabViewState({ listOpen, spaceId: "space-b" });

      expect(useChannelPaneStore.getState()).toMatchObject({
        pane: expectedPane,
        animateTransition: false,
      });
    },
  );
});
