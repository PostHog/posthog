import { beforeEach, describe, expect, it } from "vitest";
import { useThreadPanelStore } from "./threadPanelStore";

describe("threadPanelStore", () => {
  beforeEach(() => {
    useThreadPanelStore.setState({
      openByChannel: {},
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
