declare const Element: {
  new (): {
    closest(
      selector: string,
    ): { getAttribute(name: string): string | null } | null;
  };
};

export function resolveExternalAnchorUrl(target: unknown): string | null {
  const anchor = target instanceof Element ? target.closest("a[href]") : null;
  if (!anchor) return null;
  // HTML matches the _blank keyword ASCII-case-insensitively.
  if ((anchor.getAttribute("target") ?? "").toLowerCase() !== "_blank") {
    return null;
  }
  // getAttribute, not the .href property: SVG anchors expose SVGAnimatedString
  // there, and relative hrefs would resolve against the host's base URL.
  const href = anchor.getAttribute("href") ?? "";
  try {
    return new URL(href).href;
  } catch {
    return null;
  }
}
