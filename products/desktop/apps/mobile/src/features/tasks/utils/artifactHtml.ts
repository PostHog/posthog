// Mobile has no DOMParser, so this matches the meta tag at the string level
// rather than the desktop DOM-based removal.
const META_REFRESH = /<meta\b[^>]*\bhttp-equiv\s*=\s*["']?\s*refresh\b[^>]*>/gi;

export function removeAutomaticRedirects(html: string): string {
  return html.replace(META_REFRESH, "");
}
