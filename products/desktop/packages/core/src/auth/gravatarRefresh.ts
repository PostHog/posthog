export function getGravatarRefresh(
  email: string,
  refreshedAtByEmail: Record<string, number>,
  now: number,
): { email: string; refreshedAt: number } | undefined {
  const normalized = email.trim().toLowerCase();
  if (!normalized) return undefined;

  return {
    email: normalized,
    refreshedAt: Math.max(now, (refreshedAtByEmail[normalized] ?? 0) + 1),
  };
}
