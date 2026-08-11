// Benign fs stub for @posthog/agent dist bundles loaded in Storybook. The
// helpers stories use never touch the filesystem at render time; if one does,
// it gets empty results rather than a crash mid-render.
export function existsSync(): boolean {
  return false;
}

export function readFileSync(): string {
  return "";
}

export default { existsSync, readFileSync };
