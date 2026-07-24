export type OrderByField =
  | "created_at"
  | "status"
  | "title"
  | "repository"
  | "working_directory"
  | "source";

export type OrderDirection = "asc" | "desc";

export type GroupByField =
  | "none"
  | "status"
  | "creator"
  | "source"
  | "repository";

export type FilterCategory =
  | "status"
  | "source"
  | "creator"
  | "repository"
  | "created_at";

export type FilterOperator = "is" | "is_not" | "before" | "after";

export interface FilterValue {
  value: string;
  operator: FilterOperator;
}

export type ActiveFilters = Partial<Record<FilterCategory, FilterValue[]>>;

export type FilterMatchMode = "all" | "any";

export const TASK_STATUS_ORDER: string[] = [
  "failed",
  "in_progress",
  "queued",
  "completed",
  "backlog",
];

export function getDefaultOperator(category: FilterCategory): FilterOperator {
  return category === "created_at" ? "after" : "is";
}

export function toggleOperator(
  category: FilterCategory,
  operator: FilterOperator,
): FilterOperator {
  if (category === "created_at") {
    return operator === "before" ? "after" : "before";
  }
  return operator === "is" ? "is_not" : "is";
}

export function toggleFilter(
  prevFilters: ActiveFilters,
  category: FilterCategory,
  value: string,
  operator?: FilterOperator,
): ActiveFilters {
  const currentFilters = prevFilters[category] || [];
  const existingFilter = currentFilters.find((f) => f.value === value);

  if (existingFilter) {
    const newFilters = currentFilters.filter((f) => f.value !== value);
    return {
      ...prevFilters,
      [category]: newFilters.length > 0 ? newFilters : undefined,
    };
  }

  return {
    ...prevFilters,
    [category]: [
      ...currentFilters,
      { value, operator: operator ?? getDefaultOperator(category) },
    ],
  };
}

export function addFilter(
  prevFilters: ActiveFilters,
  category: FilterCategory,
  value: string,
  operator?: FilterOperator,
): ActiveFilters {
  return {
    ...prevFilters,
    [category]: [
      ...(prevFilters[category] || []),
      { value, operator: operator ?? getDefaultOperator(category) },
    ],
  };
}

export function updateFilter(
  prevFilters: ActiveFilters,
  category: FilterCategory,
  oldValue: string,
  newValue: string,
): ActiveFilters {
  const currentFilters = prevFilters[category] || [];
  const filterIndex = currentFilters.findIndex((f) => f.value === oldValue);

  if (filterIndex === -1) return prevFilters;

  const updatedFilters = [...currentFilters];
  updatedFilters[filterIndex] = {
    ...updatedFilters[filterIndex],
    value: newValue,
  };

  return {
    ...prevFilters,
    [category]: updatedFilters,
  };
}

export function toggleFilterOperator(
  prevFilters: ActiveFilters,
  category: FilterCategory,
  value: string,
): ActiveFilters {
  const currentFilters = prevFilters[category] || [];
  const filterIndex = currentFilters.findIndex((f) => f.value === value);

  if (filterIndex === -1) return prevFilters;

  const updatedFilters = [...currentFilters];
  const currentOperator = updatedFilters[filterIndex].operator;

  updatedFilters[filterIndex] = {
    ...updatedFilters[filterIndex],
    operator: toggleOperator(category, currentOperator),
  };

  return {
    ...prevFilters,
    [category]: updatedFilters,
  };
}
