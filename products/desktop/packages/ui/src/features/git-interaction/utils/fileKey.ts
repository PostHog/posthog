export function makeFileKey(staged: boolean | undefined, path: string): string {
  return `${staged ? "staged:" : "unstaged:"}${path}`;
}
