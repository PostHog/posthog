function versionTriple(version: string): number[] {
  return version
    .replace(/^v/, "")
    .split(".", 3)
    .map((segment) => Number.parseInt(segment, 10) || 0);
}

export function isVersionNewer(candidate: string, current: string): boolean {
  const a = versionTriple(candidate);
  const b = versionTriple(current);
  for (let i = 0; i < 3; i++) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) {
      return (a[i] ?? 0) > (b[i] ?? 0);
    }
  }
  return false;
}
