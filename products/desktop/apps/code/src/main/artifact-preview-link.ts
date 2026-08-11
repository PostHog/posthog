export function trustedArtifactLink({
  isTrusted,
  target,
}: Pick<MouseEvent, "isTrusted" | "target">): string | null {
  if (!isTrusted || !(target instanceof Element)) return null;
  const href = target
    .closest<HTMLAnchorElement>("a[href]")
    ?.getAttribute("href");
  if (!href) return null;
  const url = URL.parse(href);
  return url?.protocol === "http:" || url?.protocol === "https:"
    ? url.href
    : null;
}
