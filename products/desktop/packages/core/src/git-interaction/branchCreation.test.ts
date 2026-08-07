import { beforeEach, describe, expect, it, vi } from "vitest";
import { createBranch, getBranchNameInputState } from "./branchCreation";

const mockCreateBranch = vi.fn();
const writeClient = {
  createBranch: mockCreateBranch,
};

describe("branchCreation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("getBranchNameInputState", () => {
    it("sanitizes spaces and returns no error for valid names", () => {
      expect(getBranchNameInputState("feature my branch")).toEqual({
        sanitized: "feature-my-branch",
        error: null,
      });
    });

    it("returns validation errors for invalid names", () => {
      expect(getBranchNameInputState("feature..branch")).toEqual({
        sanitized: "feature..branch",
        error: 'Branch name cannot contain "..".',
      });
    });
  });

  describe("createBranch", () => {
    it("returns missing-repo error when repo path is not provided", async () => {
      const result = await createBranch({
        writeClient,
        repoPath: undefined,
        rawBranchName: "feature/test",
      });

      expect(result).toEqual({
        success: false,
        error: "Select a repository folder first.",
        reason: "missing-repo",
      });
      expect(mockCreateBranch).not.toHaveBeenCalled();
    });

    it("returns validation error for empty branch name", async () => {
      const result = await createBranch({
        writeClient,
        repoPath: "/repo",
        rawBranchName: "   ",
      });

      expect(result).toEqual({
        success: false,
        error: "Branch name is required.",
        reason: "validation",
      });
      expect(mockCreateBranch).not.toHaveBeenCalled();
    });

    it("returns validation error for invalid branch names", async () => {
      const result = await createBranch({
        writeClient,
        repoPath: "/repo",
        rawBranchName: "feature..branch",
      });

      expect(result).toEqual({
        success: false,
        error: 'Branch name cannot contain "..".',
        reason: "validation",
      });
      expect(mockCreateBranch).not.toHaveBeenCalled();
    });

    it("creates branch with trimmed name", async () => {
      mockCreateBranch.mockResolvedValueOnce(undefined);

      const result = await createBranch({
        writeClient,
        repoPath: "/repo",
        rawBranchName: "  feature/test  ",
      });

      expect(mockCreateBranch).toHaveBeenCalledWith("/repo", "feature/test");
      expect(result).toEqual({
        success: true,
        branchName: "feature/test",
      });
    });

    it("returns request error with message when mutate throws Error", async () => {
      const error = new Error("boom");
      mockCreateBranch.mockRejectedValueOnce(error);

      const result = await createBranch({
        writeClient,
        repoPath: "/repo",
        rawBranchName: "feature/test",
      });

      expect(result).toEqual({
        success: false,
        error: "boom",
        reason: "request",
        rawError: error,
      });
    });

    it("returns fallback error when mutate throws non-Error value", async () => {
      mockCreateBranch.mockRejectedValueOnce("oops");

      const result = await createBranch({
        writeClient,
        repoPath: "/repo",
        rawBranchName: "feature/test",
      });

      expect(result).toEqual({
        success: false,
        error: "Failed to create branch.",
        reason: "request",
        rawError: "oops",
      });
    });
  });
});
