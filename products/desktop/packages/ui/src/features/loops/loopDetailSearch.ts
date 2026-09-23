export function parseLoopDetailSearch(search: Record<string, unknown>): {
  edit?: boolean;
} {
  return { edit: search.edit === true || search.edit === "true" };
}
