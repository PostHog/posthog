import type { CloneOperation } from "./cloneTypes";

export function isRepoCloning(
  operations: Record<string, CloneOperation>,
  repository: string,
): boolean {
  return Object.values(operations).some(
    (op) => op.status === "cloning" && op.repository === repository,
  );
}

export function findCloneForRepo(
  operations: Record<string, CloneOperation>,
  repository: string,
): CloneOperation | null {
  return (
    Object.values(operations).find((op) => op.repository === repository) ?? null
  );
}
