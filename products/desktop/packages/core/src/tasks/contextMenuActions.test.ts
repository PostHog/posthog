import { describe, expect, it } from "vitest";
import {
  resolveBulkTaskContextMenuIntent,
  resolveExternalAppPath,
  resolveTaskContextMenuIntent,
} from "./contextMenuActions";

describe("resolveTaskContextMenuIntent", () => {
  it("maps suspend to restore when already suspended", () => {
    expect(
      resolveTaskContextMenuIntent({ type: "suspend" }, { isSuspended: true }),
    ).toEqual({ type: "restore" });
  });

  it("maps suspend to suspend when not suspended", () => {
    expect(
      resolveTaskContextMenuIntent({ type: "suspend" }, { isSuspended: false }),
    ).toEqual({ type: "suspend" });
  });

  it("passes through simple actions", () => {
    expect(resolveTaskContextMenuIntent({ type: "rename" }, {})).toEqual({
      type: "rename",
    });
    expect(resolveTaskContextMenuIntent({ type: "stop" }, {})).toEqual({
      type: "stop",
    });
    expect(resolveTaskContextMenuIntent({ type: "handoff" }, {})).toEqual({
      type: "handoff",
    });
    expect(resolveTaskContextMenuIntent({ type: "delete" }, {})).toEqual({
      type: "delete",
    });
    expect(resolveTaskContextMenuIntent({ type: "archive-prior" }, {})).toEqual(
      { type: "archive-prior" },
    );
  });

  it("carries the external-app action payload", () => {
    expect(
      resolveTaskContextMenuIntent(
        { type: "external-app", action: { type: "copy-path" } },
        {},
      ),
    ).toEqual({
      type: "external-app",
      action: { type: "copy-path" },
    });
  });
});

describe("resolveBulkTaskContextMenuIntent", () => {
  it.each([
    { allPinned: true, expected: "unpin" },
    { allPinned: false, expected: "pin" },
    { allPinned: undefined, expected: "pin" },
  ])(
    "maps pin to $expected when allPinned=$allPinned",
    ({ allPinned, expected }) => {
      expect(
        resolveBulkTaskContextMenuIntent({ type: "pin" }, { allPinned }),
      ).toEqual({ type: expected });
    },
  );

  it("passes through simple actions", () => {
    expect(resolveBulkTaskContextMenuIntent({ type: "archive" }, {})).toEqual({
      type: "archive",
    });
    expect(
      resolveBulkTaskContextMenuIntent({ type: "add-to-command-center" }, {}),
    ).toEqual({ type: "add-to-command-center" });
  });

  it("carries the channel id", () => {
    expect(
      resolveBulkTaskContextMenuIntent(
        { type: "file-to-channel", channelId: "c1" },
        {},
      ),
    ).toEqual({ type: "file-to-channel", channelId: "c1" });
  });
});

describe("resolveExternalAppPath", () => {
  it("prefers the worktree path", () => {
    expect(resolveExternalAppPath("/wt", "/folder")).toBe("/wt");
  });

  it("falls back to the folder path", () => {
    expect(resolveExternalAppPath(undefined, "/folder")).toBe("/folder");
  });

  it("returns undefined when neither present", () => {
    expect(resolveExternalAppPath(undefined, undefined)).toBeUndefined();
  });
});
