export interface LoopDetailSearch {
  edit?: boolean;
}

export function parseLoopDetailSearch(
  search: Record<string, unknown>,
): LoopDetailSearch {
  return { edit: search.edit === true || search.edit === "true" };
}
