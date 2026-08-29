import { useEffect, useState } from "react";

const DEFAULT_GRAVATAR_SIZE = 96;

// Gravatar accepts a SHA-256 hex hash of the lowercased, trimmed email, so we hash
// with the built-in Web Crypto API rather than pulling in an md5 dependency. `d=404`
// makes Gravatar return 404 (instead of a default silhouette) when the address has no
// avatar, so the <img> errors and the initials fallback stays visible.
async function gravatarUrlForEmail(
  email: string,
  size: number,
): Promise<string | undefined> {
  if (!globalThis.crypto?.subtle) return undefined;
  const normalized = email.trim().toLowerCase();
  const bytes = new TextEncoder().encode(normalized);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  const hash = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=404`;
}

export function useGravatarUrl(
  email?: string | null,
  size: number = DEFAULT_GRAVATAR_SIZE,
): string | undefined {
  const [url, setUrl] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!email) {
      setUrl(undefined);
      return;
    }
    let cancelled = false;
    // Clear any prior URL so a reused avatar whose email just changed shows
    // initials during the async hash rather than the previous person's photo.
    setUrl(undefined);
    gravatarUrlForEmail(email, size)
      .then((next) => {
        if (!cancelled) setUrl(next);
      })
      .catch(() => {
        if (!cancelled) setUrl(undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [email, size]);

  return url;
}
