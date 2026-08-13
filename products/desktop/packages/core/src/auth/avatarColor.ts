export interface AvatarColor {
  bg: string;
  text: string;
}

// Profile-avatar palette ported verbatim from PostHog's Lettermark (the 16
// --lettermark-N-bg / --lettermark-N-text pairs). Each background is paired with
// a text color picked for legible contrast, and the values are theme-independent,
// so they hold up in both light and dark mode.
const AVATAR_PALETTE: readonly AvatarColor[] = [
  { bg: "#dcb1e3", text: "#572e5e" },
  { bg: "#ffc4b2", text: "#3e5891" },
  { bg: "#b1985d", text: "#3e5891" },
  { bg: "#3e5891", text: "#ffc4b2" },
  { bg: "#8da9e7", text: "#572e5e" },
  { bg: "#572e5e", text: "#dcb1e3" },
  { bg: "#ffc035", text: "#35416b" },
  { bg: "#ff906e", text: "#2a3d65" },
  { bg: "#5dd4db", text: "#1a4a4d" },
  { bg: "#c8e65c", text: "#3d4a1a" },
  { bg: "#e85da4", text: "#4a1a35" },
  { bg: "#e85c5c", text: "#4a1a1a" },
  { bg: "#3d7a5a", text: "#c8f0dc" },
  { bg: "#6b5bd4", text: "#e0ddf5" },
  { bg: "#98e8c8", text: "#1a4a3d" },
  { bg: "#8c3d5a", text: "#f0d0dc" },
] as const;

export function avatarColorSeedHash(seed: string): number {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash + seed.charCodeAt(i) * (i + 1)) % 9973;
  }
  return hash;
}

// Picks a stable palette entry for a seed, mirroring Lettermark's `index % 16`
// variant selection.
export function avatarColor(seed: string): AvatarColor {
  return AVATAR_PALETTE[avatarColorSeedHash(seed) % AVATAR_PALETTE.length];
}
