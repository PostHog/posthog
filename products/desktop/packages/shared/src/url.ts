const SAFE_EXTERNAL_URL_SCHEMES: ReadonlySet<string> = new Set([
  "http:",
  "https:",
  "mailto:",
]);

/**
 * Whether a URL is safe to hand to the host's "open externally" capability,
 * which ultimately reaches `shell.openExternal` and dispatches to whatever app
 * the OS has registered for the scheme. Restricting to web and mail schemes
 * stops a tampered or attacker-supplied value from triggering `file:`, `smb:`,
 * `data:`, `javascript:`, `ms-msdt:`, or custom app deep-link schemes.
 */
export function isSafeExternalUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return SAFE_EXTERNAL_URL_SCHEMES.has(parsed.protocol);
}

/**
 * Whether a URL from untrusted code (the freeform-canvas sandbox) may be
 * opened externally: absolute https URLs on posthog.com or a subdomain only.
 */
export function isSafePostHogUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return (
    parsed.protocol === "https:" &&
    (parsed.hostname === "posthog.com" ||
      parsed.hostname.endsWith(".posthog.com"))
  );
}
