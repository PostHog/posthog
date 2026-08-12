import { describe, expect, it } from "vitest";
import { parseUnarchiveError } from "./parseUnarchiveError";

describe("parseUnarchiveError", () => {
  it("extracts the branch name when the branch is missing", () => {
    const result = parseUnarchiveError(
      new Error("Branch 'feature/x' does not exist"),
    );
    expect(result).toEqual({
      kind: "branch-not-found",
      branchName: "feature/x",
    });
  });

  it("returns the raw message for other errors", () => {
    const result = parseUnarchiveError(new Error("network down"));
    expect(result).toEqual({ kind: "other", message: "network down" });
  });

  it("coerces non-error values to a string message", () => {
    const result = parseUnarchiveError("boom");
    expect(result).toEqual({ kind: "other", message: "boom" });
  });
});
