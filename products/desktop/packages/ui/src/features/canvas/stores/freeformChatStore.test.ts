import { beforeEach, describe, expect, it } from "vitest";
import {
  EMPTY_FREEFORM_THREAD,
  useFreeformChatStore,
} from "./freeformChatStore";

function reset() {
  useFreeformChatStore.setState({ threads: {} });
}

describe("freeformChatStore", () => {
  beforeEach(reset);

  it("creates a thread from the empty state on first patch", () => {
    useFreeformChatStore.getState().setBrowseVersion("dashboard:1", "v1");

    expect(useFreeformChatStore.getState().threads["dashboard:1"]).toEqual({
      ...EMPTY_FREEFORM_THREAD,
      browseVersionId: "v1",
    });
  });

  it("patches fields independently per thread", () => {
    const store = useFreeformChatStore.getState();
    store.setBrowseVersion("dashboard:1", "v1");
    store.setRuntimeError("dashboard:1", "boom");
    store.setRuntimeError("dashboard:2", "other");

    const { threads } = useFreeformChatStore.getState();
    expect(threads["dashboard:1"]).toEqual({
      browseVersionId: "v1",
      displayedVersionId: null,
      runtimeError: "boom",
    });
    expect(threads["dashboard:2"]).toEqual({
      browseVersionId: null,
      displayedVersionId: null,
      runtimeError: "other",
    });
  });

  it("clears a field back to null without dropping the thread", () => {
    const store = useFreeformChatStore.getState();
    store.setBrowseVersion("dashboard:1", "v1");
    store.setBrowseVersion("dashboard:1", null);

    expect(useFreeformChatStore.getState().threads["dashboard:1"]).toEqual(
      EMPTY_FREEFORM_THREAD,
    );
  });

  it("tracks the immutable version currently rendered", () => {
    useFreeformChatStore
      .getState()
      .setDisplayedVersion("dashboard:1", "version-2");

    expect(
      useFreeformChatStore.getState().threads["dashboard:1"]
        ?.displayedVersionId,
    ).toBe("version-2");
  });
});
