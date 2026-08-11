import { describe, expect, it } from "vitest";
import { artifactFilesListKey } from "./artifactFilesListKey";

describe("artifactFilesListKey", () => {
  it("ignores file order", () => {
    expect(artifactFilesListKey("r1", ["b.md", "a.md"])).toBe(
      artifactFilesListKey("r1", ["a.md", "b.md"]),
    );
  });

  it("changes when the set of files changes", () => {
    expect(artifactFilesListKey("r1", ["a.md"])).not.toBe(
      artifactFilesListKey("r1", ["a.md", "b.md"]),
    );
  });

  it("changes with the run", () => {
    expect(artifactFilesListKey("r1", ["a.md"])).not.toBe(
      artifactFilesListKey("r2", ["a.md"]),
    );
  });
});
