import { describe, expect, it } from "vitest";
import { parseCloneProgress } from "./cloneProgress";
import type { CloneOperation } from "./cloneTypes";

const operation = (latestMessage?: string): CloneOperation => ({
  cloneId: "c1",
  repository: "owner/repo",
  targetPath: "/tmp/repo",
  status: "cloning",
  latestMessage,
});

describe("parseCloneProgress", () => {
  it("returns null for a null operation", () => {
    expect(parseCloneProgress(null)).toBeNull();
  });

  it("returns null when there is no latest message", () => {
    expect(parseCloneProgress(operation(undefined))).toBeNull();
  });

  it("extracts the percent integer from the message", () => {
    expect(parseCloneProgress(operation("Receiving objects: 42%"))).toEqual({
      message: "Receiving objects: 42%",
      percent: 42,
    });
  });

  it("defaults percent to 0 when no percent is present", () => {
    expect(parseCloneProgress(operation("Cloning owner/repo..."))).toEqual({
      message: "Cloning owner/repo...",
      percent: 0,
    });
  });
});
