import type { CanvasArtifactFile } from "./canvas-build-contract";

// Folds a built canvas artifact into one self-contained HTML document the
// existing null-origin iframe host can load (srcdoc), replacing the legacy
// preview path's in-browser Babel + Tailwind JIT with ahead-of-time build
// output. Only the pinned platform-dependency host remains reachable — the
// emitted application code itself is inlined.

const PREVIEW_DEPENDENCY_HOST = "https://esm.sh";

// srcdoc previews have no response headers, so the policy rides in a meta tag.
// frame-ancestors/report-uri are ignored in meta CSP; everything else applies.
const PREVIEW_CSP = [
  "default-src 'none'",
  `script-src 'unsafe-inline' ${PREVIEW_DEPENDENCY_HOST}`,
  `style-src 'unsafe-inline' ${PREVIEW_DEPENDENCY_HOST}`,
  `font-src ${PREVIEW_DEPENDENCY_HOST} data:`,
  "img-src data: blob:",
  `connect-src ${PREVIEW_DEPENDENCY_HOST}`,
].join("; ");

function escapeClosingTags(content: string, tag: string): string {
  return content.replaceAll(`</${tag}`, `<\\/${tag}`);
}

/**
 * Inline every emitted asset the entry HTML references, producing a single
 * document with a strict CSP. Returns null when the artifact has no entry
 * HTML (a failed or empty build has nothing to preview).
 */
export function renderCanvasPreviewDocument(
  files: CanvasArtifactFile[],
  entryHtml = "index.html",
): string | null {
  const entry = files.find((file) => file.path === entryHtml);
  if (!entry) return null;

  let html = entry.content;
  for (const file of files) {
    if (file.path === entryHtml) continue;
    const ref = `./${file.path}`;
    if (file.path.endsWith(".js")) {
      const scriptTag = new RegExp(
        `<script\\s[^>]*src\\s*=\\s*["']${ref.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["'][^>]*>\\s*</script>`,
        "i",
      );
      html = html.replace(
        scriptTag,
        `<script type="module">${escapeClosingTags(file.content, "script")}</script>`,
      );
    } else if (file.path.endsWith(".css")) {
      const linkTag = new RegExp(
        `<link\\s[^>]*href\\s*=\\s*["']${ref.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["'][^>]*/?>`,
        "i",
      );
      html = html.replace(
        linkTag,
        `<style>${escapeClosingTags(file.content, "style")}</style>`,
      );
    }
  }

  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}" />`;
  return html.includes("<head>")
    ? html.replace("<head>", `<head>\n    ${cspMeta}`)
    : `${cspMeta}\n${html}`;
}
