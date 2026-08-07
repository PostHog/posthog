export function trustedArtifactLink({
  isTrusted,
  target,
}: Pick<MouseEvent, "isTrusted" | "target">): string | null {
  if (!isTrusted || !(target instanceof Element)) return null;
  return target.closest<HTMLAnchorElement>("a[href]")?.href ?? null;
}
