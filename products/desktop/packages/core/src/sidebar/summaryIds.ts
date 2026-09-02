export function computeSummaryIds(input: {
  workspaceIds: Iterable<string>;
  pinnedTaskIds: Iterable<string>;
  provisioningTaskIds: Iterable<string>;
  archivedTaskIds: Iterable<string>;
}): string[] {
  const ids = new Set<string>();
  for (const id of input.workspaceIds) ids.add(id);
  for (const id of input.pinnedTaskIds) ids.add(id);
  for (const id of input.provisioningTaskIds) ids.add(id);
  for (const id of input.archivedTaskIds) ids.delete(id);
  return Array.from(ids);
}
