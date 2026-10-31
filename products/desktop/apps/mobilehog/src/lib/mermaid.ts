const MERMAID_LANGUAGE = "mermaid";

export function isMermaidLang(lang: string | undefined): boolean {
  return lang?.trim().split(/\s+/)[0].toLowerCase() === MERMAID_LANGUAGE;
}

// A fence without its closing line is still streaming; rendering each partial
// diagram would reload the WebView on every token.
export function isClosedFence(raw: string): boolean {
  const open = /^ {0,3}(`{3,}|~{3,})/.exec(raw);
  if (!open) return false;
  const fence = open[1];
  const lines = raw.trimEnd().split("\n");
  if (lines.length < 2) return false;
  const last = lines[lines.length - 1].trim();
  return (
    last.length >= fence.length &&
    /^(`+|~+)$/.test(last) &&
    last[0] === fence[0]
  );
}

// The `img` key of a shape metadata block, as in `A@{ img: "…" }`. Mermaid reads the key
// case sensitively today, but matching either case keeps the guard off that detail.
const IMAGE_NODE =
  /(?:^|[,{\s])["']?img["']?\s*:\s*(?<url>"[^"]*"|'[^']*'|[^,}\n]*)/gi;

// Mermaid loads an image node through `new Image()` while it builds the SVG, before
// DOMPurify ever sees the output. Diagrams reach us from agent output, so a remote
// image node would let their author make the app fetch any URL.
export function hasRemoteImageNode(code: string): boolean {
  for (const node of code.matchAll(IMAGE_NODE)) {
    const url = node.groups?.url?.trim() ?? "";
    if (!/^["']?data:/i.test(url)) return true;
  }
  return false;
}

export interface DiagramSize {
  width: number;
  height: number;
}

export type MermaidMessage =
  | ({ type: "size" } & DiagramSize)
  | { type: "error" };

export function parseMermaidMessage(data: string): MermaidMessage | null {
  let message: unknown;
  try {
    message = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof message !== "object" || message === null) return null;
  const { type, width, height } = message as Record<string, unknown>;
  if (type === "error") return { type };
  if (
    type === "size" &&
    typeof width === "number" &&
    typeof height === "number" &&
    width > 0 &&
    height > 0
  ) {
    return { type, width, height };
  }
  return null;
}

export function rememberSize(
  cache: Map<string, DiagramSize>,
  key: string,
  size: DiagramSize,
  limit: number,
): void {
  cache.delete(key);
  cache.set(key, size);
  for (const oldest of cache.keys()) {
    if (cache.size <= limit) break;
    cache.delete(oldest);
  }
}

// Embeds a value in an inline script without letting it close the tag.
function scriptLiteral(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

// Keeps a script source from ending its tag early. The escape only appears in
// strings, regexes and comments, where it still reads as "<".
export function inlineScriptSource(source: string): string {
  return source.replace(/<(?=!--|\/?script)/gi, "\\x3C");
}

// The bundle loads in its own script tag before the render script. Injected
// JavaScript runs inside a function on Android, where the bundle's top-level
// `var` does not become a global, and it may run after the page scripts. The
// policy blocks every network fetch, so the SVG can only use what it carries.
export function mermaidHtml(
  code: string,
  dark: boolean,
  bundle: string,
): string {
  const config = {
    startOnLoad: false,
    theme: dark ? "dark" : "default",
    securityLevel: "strict",
    suppressErrorRendering: true,
    fontFamily: "-apple-system, system-ui, sans-serif",
  };
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:">
<style>html, body { margin: 0; padding: 0; background: transparent; overflow: hidden; } svg { display: block; }</style>
</head>
<body>
<div id="root"></div>
<script>${bundle}</script>
<script>
(function () {
  function post(message) {
    window.ReactNativeWebView.postMessage(JSON.stringify(message));
  }
  function fail() {
    post({ type: "error" });
  }
  if (!window.mermaid) return fail();
  try {
    mermaid.initialize(${scriptLiteral(config)});
    mermaid.render("diagram", ${scriptLiteral(code)}).then(function (result) {
      var root = document.getElementById("root");
      root.innerHTML = result.svg;
      var svg = root.querySelector("svg");
      if (!svg) return fail();
      var box = svg.viewBox && svg.viewBox.baseVal;
      var rect = svg.getBoundingClientRect();
      var width = Math.ceil(box && box.width ? box.width : rect.width);
      var height = Math.ceil(box && box.height ? box.height : rect.height);
      svg.style.maxWidth = "none";
      svg.setAttribute("width", String(width));
      svg.setAttribute("height", String(height));
      post({ type: "size", width: width, height: height });
    }, fail);
  } catch (error) {
    fail();
  }
})();
</script>
</body>
</html>`;
}
