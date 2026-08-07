export function resolvePendingPermissionVisibility(
  override: boolean | undefined,
  storedCount: number,
): boolean {
  return override ?? storedCount > 0;
}
