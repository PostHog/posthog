import type { ChangedFile } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  buildChangeTree,
  compactChangeTree,
  flattenChangeTree,
  orderPathsLikeChangeTree,
  sortByChangeTreeOrder,
} from "./changeTree";

const file = (path: string, over: Partial<ChangedFile> = {}): ChangedFile => ({
  path,
  status: "modified",
  ...over,
});

const paths = (files: ChangedFile[]) => files.map((f) => f.path);

describe("buildChangeTree", () => {
  it("nests files under their directory parts", () => {
    const tree = buildChangeTree([
      file("src/a.ts"),
      file("src/utils/b.ts"),
      file("root.ts"),
    ]);
    expect(tree.files.map((f) => f.path)).toEqual(["root.ts"]);
    expect([...tree.children.keys()]).toEqual(["src"]);
    const src = tree.children.get("src");
    expect(src?.files.map((f) => f.path)).toEqual(["src/a.ts"]);
    expect([...(src?.children.keys() ?? [])]).toEqual(["utils"]);
  });
});

describe("compactChangeTree", () => {
  it("collapses single-child directory chains into one node", () => {
    const tree = compactChangeTree(buildChangeTree([file("src/a/b/c.ts")]));
    const src = tree.children.get("src");
    expect(src?.name).toBe("src/a/b");
    expect(src?.files.map((f) => f.path)).toEqual(["src/a/b/c.ts"]);
  });

  it("does not collapse a directory that holds files", () => {
    const tree = compactChangeTree(
      buildChangeTree([file("src/a/b.ts"), file("src/c.ts")]),
    );
    const src = tree.children.get("src");
    expect(src?.name).toBe("src");
    expect([...(src?.children.keys() ?? [])]).toEqual(["a"]);
  });
});

describe("flattenChangeTree", () => {
  it("groups a directory's files together ahead of later siblings", () => {
    const ordered = flattenChangeTree([
      file("zeta.txt"),
      file("alpha.txt"),
      file("src/mid.ts"),
      file("src/beta.ts"),
    ]);
    // Directories sort before sibling files at every node, so the src/ group
    // precedes root-level alpha.txt and zeta.txt.
    expect(paths(ordered)).toEqual([
      "src/beta.ts",
      "src/mid.ts",
      "alpha.txt",
      "zeta.txt",
    ]);
  });

  it("sorts case-insensitively, matching the file tree (not git byte order)", () => {
    const ordered = flattenChangeTree([
      file("Beta.txt"),
      file("ZETA_CAPS.txt"),
      file("alpha.txt"),
      file("zeta.txt"),
    ]);
    expect(paths(ordered)).toEqual([
      "alpha.txt",
      "Beta.txt",
      "ZETA_CAPS.txt",
      "zeta.txt",
    ]);
  });

  it("interleaves untracked files with modified ones by path", () => {
    const ordered = flattenChangeTree([
      file("a.ts", { status: "modified" }),
      file("untracked.ts", { status: "untracked" }),
      file("b.ts", { status: "modified" }),
    ]);
    expect(paths(ordered)).toEqual(["a.ts", "b.ts", "untracked.ts"]);
  });

  it("sorts files within a directory by basename", () => {
    const ordered = flattenChangeTree([
      file("src/mid.ts"),
      file("src/Apple.ts"),
      file("src/beta.ts"),
    ]);
    expect(paths(ordered)).toEqual([
      "src/Apple.ts",
      "src/beta.ts",
      "src/mid.ts",
    ]);
  });

  it("renders directories before sibling files at every level", () => {
    const ordered = flattenChangeTree([
      file("root_file.ts"),
      file("dir/inside.ts"),
    ]);
    expect(paths(ordered)).toEqual(["dir/inside.ts", "root_file.ts"]);
  });

  it("returns an empty list for no files", () => {
    expect(flattenChangeTree([])).toEqual([]);
  });
});

describe("orderPathsLikeChangeTree", () => {
  it("orders paths like the file tree, not git byte order", () => {
    expect(
      orderPathsLikeChangeTree([
        "Beta.txt",
        "ZETA_CAPS.txt",
        "alpha.txt",
        "src/Apple.ts",
        "src/beta.ts",
        "zeta.txt",
      ]),
    ).toEqual([
      "src/Apple.ts",
      "src/beta.ts",
      "alpha.txt",
      "Beta.txt",
      "ZETA_CAPS.txt",
      "zeta.txt",
    ]);
  });

  it("returns an empty list for no paths", () => {
    expect(orderPathsLikeChangeTree([])).toEqual([]);
  });
});

describe("sortByChangeTreeOrder", () => {
  const item = (key: string, filePaths: string[]) => ({ key, filePaths });

  it("reorders items to match the given tree order", () => {
    const items = [
      item("a", ["zeta.txt"]),
      item("b", ["alpha.txt"]),
      item("c", ["src/x.ts"]),
    ];
    const ordered = sortByChangeTreeOrder(items, [
      "src/x.ts",
      "alpha.txt",
      "zeta.txt",
    ]);
    expect(ordered.map((i) => i.key)).toEqual(["c", "b", "a"]);
  });

  it("keeps items whose path is not in the order last", () => {
    const items = [item("a", ["unknown.ts"]), item("b", ["alpha.txt"])];
    const ordered = sortByChangeTreeOrder(items, ["alpha.txt"]);
    expect(ordered.map((i) => i.key)).toEqual(["b", "a"]);
  });

  it("returns the same array reference when there is no tree order", () => {
    const items = [item("a", ["zeta.txt"]), item("b", ["alpha.txt"])];
    expect(sortByChangeTreeOrder(items, [])).toBe(items);
  });
});
