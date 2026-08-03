import { describe, expect, it } from "vitest";
import { getNewAttachments } from "./SessionView";

describe("getNewAttachments", () => {
  it("returns only attachments that were not already present", () => {
    const attachments = [
      { id: "/tmp/existing.png", label: "existing.png" },
      { id: "/tmp/new.png", label: "new.png" },
    ];

    expect(
      getNewAttachments(new Set(["/tmp/existing.png"]), attachments),
    ).toEqual([attachments[1]]);
  });

  it("allows a removed attachment to be uploaded again", () => {
    const attachment = { id: "/tmp/retry.png", label: "retry.png" };

    expect(getNewAttachments(new Set(), [attachment])).toEqual([attachment]);
  });
});
