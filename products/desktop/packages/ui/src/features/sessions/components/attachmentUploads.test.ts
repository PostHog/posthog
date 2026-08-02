import { describe, expect, it } from "vitest";
import { getAddedAttachments } from "./attachmentUploads";

describe("getAddedAttachments", () => {
  it("only returns attachments added since the previous change", () => {
    expect(
      getAddedAttachments(new Set(["/tmp/first.png"]), [
        { id: "/tmp/first.png", label: "first.png" },
        { id: "/tmp/second.png", label: "second.png" },
      ]),
    ).toEqual([{ id: "/tmp/second.png", label: "second.png" }]);
  });

  it("treats a removed and re-added attachment as new", () => {
    expect(
      getAddedAttachments(new Set(), [
        { id: "/tmp/retry.png", label: "retry.png" },
      ]),
    ).toEqual([{ id: "/tmp/retry.png", label: "retry.png" }]);
  });
});
