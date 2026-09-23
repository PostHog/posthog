type BlocksMath = "total" | "dau" | "weekly_active" | "monthly_active";

export const MATH_OPTIONS: Array<{ value: BlocksMath; label: string }> = [
  { value: "total", label: "Total count" },
  { value: "dau", label: "Unique users" },
  { value: "weekly_active", label: "Weekly active users" },
  { value: "monthly_active", label: "Monthly active users" },
];

export function mathLabel(value: BlocksMath): string {
  return MATH_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function eventLabel(event: string): string {
  const known: Record<string, string> = {
    $pageview: "Pageview",
    $pageleave: "Pageleave",
    $autocapture: "Autocapture",
    $screen: "Screen",
    $identify: "Identify",
    $exception: "Exception",
    $web_vitals: "Web vitals",
    $feature_flag_called: "Feature flag called",
    $groupidentify: "Group identify",
    $set: "Set person properties",
  };
  if (known[event]) return known[event];
  if (!event.startsWith("$")) return event;
  const words = event.slice(1).replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
