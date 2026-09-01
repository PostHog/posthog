import { useEffect, useState } from "react";

const DEFAULT_GRAVATAR_SIZE = 96;

// Gravatar accepts a SHA-256 hex hash of the lowercased, trimmed email, so we hash
// with the built-in Web Crypto API rather than pulling in an md5 dependency. `d=404`
// makes Gravatar return 404 (instead of a default silhouette) when the address has no
// avatar, so the <img> errors and the initials fallback stays visible.
async function gravatarUrlForEmail(
  normalizedEmail: string,
  size: number,
): Promise<string | undefined> {
  if (!globalThis.crypto?.subtle) return undefined;
  const bytes = new TextEncoder().encode(normalizedEmail);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  const hash = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=404`;
}

const gravatarUrls = new Map<string, string>();

function cacheKey(normalizedEmail: string, size: number): string {
  return `${normalizedEmail}:${size}`;
}

interface HashedGravatar {
  key: string;
  url: string | undefined;
}

export function useGravatarUrl(
  email?: string | null,
  size: number = DEFAULT_GRAVATAR_SIZE,
): string | undefined {
  const normalized = email?.trim().toLowerCase() || undefined;
  const key = normalized ? cacheKey(normalized, size) : undefined;
  const cached = key ? gravatarUrls.get(key) : undefined;
  const [hashed, setHashed] = useState<HashedGravatar | null>(null);

  useEffect(() => {
    if (!normalized || cached) return;
    const pendingKey = cacheKey(normalized, size);
    let cancelled = false;
    gravatarUrlForEmail(normalized, size)
      .then((url) => {
        if (url) gravatarUrls.set(pendingKey, url);
        if (!cancelled) setHashed({ key: pendingKey, url });
      })
      .catch(() => {
        if (!cancelled) setHashed({ key: pendingKey, url: undefined });
      });
    return () => {
      cancelled = true;
    };
  }, [normalized, size, cached]);

  if (cached) return cached;
  return hashed && hashed.key === key ? hashed.url : undefined;
}
