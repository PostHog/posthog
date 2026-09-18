import { beforeEach, describe, expect, it } from "vitest";
import { useThreadPanelStore } from "./threadPanelStore";

describe("threadPanelStore", () => {
  beforeEach(() => {
    useThreadPanelStore.setState({
      openByChannel: {},
      tabRequestByTask: {},
      collapsed: false,
      width: 360,
    });
  });

  it("keeps each channel tab's open thread independent", () => {
    const { openThread } = useThreadPanelStore.getState();

    openThread("channel-a", "task-a");
    openThread("channel-b", "task-b");

    expect(useThreadPanelStore.getState().openByChannel).toEqual({
      "channel-a": "task-a",
      "channel-b": "task-b",
    });
  });

  it("drops a tab request once consumed, so a remounting panel can't replay it", () => {
    const { openThread, consumeTabRequest } = useThreadPanelStore.getState();

    openThread("channel-a", "task-a", { tab: "comments" });
    const request = useThreadPanelStore.getState().tabRequestByTask["task-a"];
    expect(request?.tab).toBe("comments");

    consumeTabRequest("task-a", request?.nonce ?? -1);

    expect(
      useThreadPanelStore.getState().tabRequestByTask["task-a"],
    ).toBeUndefined();
  });

  it("keeps a newer tab request when a stale ack arrives", () => {
    const { openThread, consumeTabRequest } = useThreadPanelStore.getState();

    openThread("channel-a", "task-a", { tab: "comments" });
    const first = useThreadPanelStore.getState().tabRequestByTask["task-a"];
    openThread("channel-a", "task-a", { tab: "artifacts" });

    consumeTabRequest("task-a", first?.nonce ?? -1);

    expect(useThreadPanelStore.getState().tabRequestByTask["task-a"]?.tab).toBe(
      "artifacts",
    );
  });

  it("closes only the active channel's thread", () => {
    useThreadPanelStore.setState({
      openByChannel: { "channel-a": "task-a", "channel-b": "task-b" },
    });

    useThreadPanelStore.getState().closeThread("channel-a");

    expect(useThreadPanelStore.getState().openByChannel).toEqual({
      "channel-a": null,
      "channel-b": "task-b",
    });
  });
});
