import type { FileTreeNode } from "@posthog/ui/primitives/FileExplorer";

/**
 * Folds the tree endpoint's flat path list into a FileExplorer tree.
 * Within a directory, pages come before subdirectories and sort
 * alphabetically — except AGENTS.md, which leads its directory because it is
 * the wiki's entry page. Directories carry no `path`, so they toggle rather
 * than select.
 */
export function buildWikiTree(paths: string[]): FileTreeNode {
  const root: FileTreeNode = { type: "folder", name: "", children: [] };
  const dirsByPath = new Map<string, FileTreeNode>([["", root]]);

  const ensureDir = (dirPath: string): FileTreeNode => {
    const existing = dirsByPath.get(dirPath);
    if (existing) return existing;
    const separator = dirPath.lastIndexOf("/");
    const parent = ensureDir(
      separator === -1 ? "" : dirPath.slice(0, separator),
    );
    const dir: FileTreeNode = {
      type: "folder",
      name: dirPath.slice(separator + 1),
      children: [],
    };
    parent.children?.push(dir);
    dirsByPath.set(dirPath, dir);
    return dir;
  };

  for (const path of paths) {
    const separator = path.lastIndexOf("/");
    const dir = ensureDir(separator === -1 ? "" : path.slice(0, separator));
    const fileName = path.slice(separator + 1);
    dir.children?.push({
      type: "file",
      name: fileName.replace(/\.md$/, ""),
      path,
    });
  }

  for (const dir of dirsByPath.values()) {
    dir.children?.sort((a, b) => {
      if (a.type !== b.type) return a.type === "file" ? -1 : 1;
      if (a.name === "AGENTS" && a.type === "file") return -1;
      if (b.name === "AGENTS" && b.type === "file") return 1;
      return a.name.localeCompare(b.name);
    });
  }
  return root;
}
