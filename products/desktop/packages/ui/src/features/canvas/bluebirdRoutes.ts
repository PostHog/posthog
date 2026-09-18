/**
 * Paths that only exist inside project-bluebird: the spaces themselves, the
 * activity feed and a feed page.
 *
 * These used to sit behind a `/website` prefix, which was the flag-off check.
 * Flattening the routes took the prefix away, so the paths are listed here
 * instead — a flag-off user restoring one has to be sent somewhere they can use.
 */
const BLUEBIRD_ONLY_ROOTS = [
  "/spaces",
  "/activity",
  "/feeds",
  "/canvases",
] as const;

export function isBluebirdOnlyPath(pathname: string): boolean {
  return BLUEBIRD_ONLY_ROOTS.some(
    (root) => pathname === root || pathname.startsWith(`${root}/`),
  );
}
