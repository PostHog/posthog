export function taskSearchDelay(query: string): number | null {
  const trimmed = query.trim();
  if (!/^#?\d+$/.test(trimmed) && trimmed.length < 2) return null;
  return /^https?:\/\//i.test(trimmed) ? 0 : 120;
}
