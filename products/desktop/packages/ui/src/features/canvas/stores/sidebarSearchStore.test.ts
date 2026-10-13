import { beforeEach, describe, expect, it } from "vitest";
import {
  requestSidebarSearchFocus,
  useSidebarSearchStore,
} from "./sidebarSearchStore";

describe("sidebarSearchStore", () => {
  beforeEach(() => {
    useSidebarSearchStore.setState({ focusRequest: 0 });
  });

  it("claims a pending focus request once, then never again", () => {
    requestSidebarSearchFocus();
    const token = useSidebarSearchStore.getState().focusRequest;
    expect(token).toBe(1);

    const { claimFocus } = useSidebarSearchStore.getState();
    expect(claimFocus(token)).toBe(true);
    expect(useSidebarSearchStore.getState().focusRequest).toBe(0);
    // A header that mounts later reads the same stale token and must not refocus.
    expect(claimFocus(token)).toBe(false);
  });

  it.each([
    ["the token is the empty sentinel", 0],
    ["the token does not match the pending request", 2],
  ])("leaves the request pending when %s", (_case, token) => {
    requestSidebarSearchFocus();
    expect(useSidebarSearchStore.getState().claimFocus(token)).toBe(false);
    expect(useSidebarSearchStore.getState().focusRequest).toBe(1);
  });
});
