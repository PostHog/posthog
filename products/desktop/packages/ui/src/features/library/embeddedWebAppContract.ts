/**
 * The shapes `mountLegacyApp` takes and returns. The source of truth is
 * `frontend/src/embed/embedTypes.ts` in the monorepo, which this workspace cannot import, so this is
 * a copy. The web app reports the version it speaks, and Library refuses to run a different one.
 */
export const EMBED_API_VERSION = 1;

export interface EmbedLocation {
  pathname: string;
  search: string;
  hash: string;
}

export interface EmbedHost {
  backendHost: string;
  getAccessToken: () => string;
  refreshAccessToken: () => Promise<string | null>;
  getLocation: () => EmbedLocation;
  navigate: (url: string, options: { replace: boolean }) => void;
  signOut: () => void;
  theme: "light" | "dark";
  analytics?: { apiKey: string; apiHost: string };
}

export interface EmbedHandle {
  apiVersion: number;
  syncLocation: () => void;
  setTheme: (theme: EmbedHost["theme"]) => void;
  unmount: () => void;
}

export type MountLegacyApp = (
  element: HTMLElement,
  host: EmbedHost,
) => EmbedHandle;
