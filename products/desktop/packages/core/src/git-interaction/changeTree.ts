import type { ChangedFile } from "@posthog/shared/domain-types";

export interface ChangeTreeNode {
  name: string;
  path: string;
  children: Map<string, ChangeTreeNode>;
  files: ChangedFile[];
}

export function buildChangeTree(files: ChangedFile[]): ChangeTreeNode {
  const root: ChangeTreeNode = {
    name: "",
    path: "",
    children: new Map(),
    files: [],
  };
  for (const file of files) {
    const parts = file.path.split("/");
    let node = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!node.children.has(part)) {
        node.children.set(part, {
          name: part,
          path: parts.slice(0, i + 1).join("/"),
          children: new Map(),
          files: [],
        });
      }
      const child = node.children.get(part);
      if (!child) break;
      node = child;
    }
    node.files.push(file);
  }
  return root;
}

export function compactChangeTree(node: ChangeTreeNode): ChangeTreeNode {
  const compacted = new Map<string, ChangeTreeNode>();
  for (const [key, child] of node.children) {
    let current = child;
    let label = current.name;
    while (current.children.size === 1 && current.files.length === 0) {
      const [, only] = [...current.children.entries()][0];
      label = `${label}/${only.name}`;
      current = only;
    }
    const result = compactChangeTree(current);
    result.name = label;
    compacted.set(key, result);
  }
  return { ...node, children: compacted };
}

const compareLocale = (a: string, b: string) => a.localeCompare(b);

export function orderedTreeDirs(node: ChangeTreeNode): ChangeTreeNode[] {
  return [...node.children.values()].sort((a, b) =>
    compareLocale(a.name, b.name),
  );
}

export function orderedTreeFiles(node: ChangeTreeNode): ChangedFile[] {
  return [...node.files].sort((a, b) => {
    const aName = a.path.split("/").pop() ?? "";
    const bName = b.path.split("/").pop() ?? "";
    return compareLocale(aName, bName);
  });
}

function flattenNode(node: ChangeTreeNode, out: ChangedFile[]) {
  for (const child of orderedTreeDirs(node)) {
    flattenNode(child, out);
  }
  for (const file of orderedTreeFiles(node)) {
    out.push(file);
  }
}

export function flattenChangeTree(files: ChangedFile[]): ChangedFile[] {
  const tree = compactChangeTree(buildChangeTree(files));
  const out: ChangedFile[] = [];
  flattenNode(tree, out);
  return out;
}

export function orderPathsLikeChangeTree(paths: string[]): string[] {
  const file = (path: string): ChangedFile => ({ path, status: "modified" });
  return flattenChangeTree(paths.map(file)).map((f) => f.path);
}

export function sortByChangeTreeOrder<T extends { filePaths?: string[] }>(
  items: T[],
  orderedPaths: string[],
): T[] {
  if (orderedPaths.length === 0) return items;

  const order = new Map<string, number>();
  for (let i = 0; i < orderedPaths.length; i++) {
    order.set(orderedPaths[i], i);
  }

  const rank = (item: T): number => {
    const path = item.filePaths?.find((p) => order.has(p));
    return path !== undefined
      ? (order.get(path) ?? Number.MAX_SAFE_INTEGER)
      : Number.MAX_SAFE_INTEGER;
  };

  return [...items].sort((a, b) => rank(a) - rank(b));
}
