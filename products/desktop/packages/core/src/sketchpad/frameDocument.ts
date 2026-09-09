import {
  CANVAS_SDK_SPECIFIER,
  SKETCHPAD_ALLOWED_IMPORTS,
  SKETCHPAD_CHANNEL,
  SKETCHPAD_FIELD_MAX_ENTRIES,
  SKETCHPAD_MAX_STATE_VALUE_BYTES,
  SKETCHPAD_MODULE_SCHEME,
  SKETCHPAD_TAILWIND_PREFIX,
  vendoredModuleUrl,
} from "@posthog/shared";
import {
  buildImportMap,
  FREEFORM_ESM_HOST,
  FREEFORM_QUILL_CSS_URLS,
} from "../canvas/freeformWhitelist";
import { resolveExternalAnchorUrl } from "../canvas/sandboxLinks";
import { createFragmentCompiler } from "./fragmentCompiler";
import sketchpadBootstrapRaw from "./frame/sketchpadBootstrap.js?raw";
import sketchpadFrameRaw from "./frame/sketchpadFrame.css?raw";
import sketchpadSdkRaw from "./frame/sketchpadSdk.js?raw";
import sketchpadThemeRaw from "./frame/sketchpadTheme.css?raw";
import {
  SHARED_FIELD_READ_ONLY_STATE,
  SHARED_TEXT_FULL,
  SKETCHPAD_FRAGMENT_ERROR_HINT,
  SKETCHPAD_FRAGMENT_ERROR_TITLE,
} from "./frameCopy";
import { containsFragmentCenter } from "./sketchpadGeometry";

const TAILWIND_URL = `${SKETCHPAD_TAILWIND_PREFIX}browser@4.3.1`;

const TAILWIND_STYLE = `<style type="text/tailwindcss">${sketchpadThemeRaw}</style>`;

export const SKETCHPAD_FRAME_SDK_MODULE_SOURCE = fillSource(sketchpadSdkRaw, {
  __PH_CONTAINS_CENTER__: containsFragmentCenter.toString(),
  __PH_MAX_FIELD_ENTRIES__: String(SKETCHPAD_FIELD_MAX_ENTRIES),
  __PH_TEXT_FULL__: JSON.stringify(SHARED_TEXT_FULL),
});

export interface SketchpadFrameOptions {
  vendoredModules: boolean;
}

export function buildSketchpadFrameDocument(
  options: SketchpadFrameOptions,
): string {
  const moduleUrl = (url: string): string =>
    options.vendoredModules ? vendoredModuleUrl(url) : url;
  const map = buildImportMap();
  const importMap = JSON.stringify({
    imports: Object.fromEntries(
      Object.entries(map.imports).map(([name, url]) => [name, moduleUrl(url)]),
    ),
  });
  const csp = sketchpadFramePolicy(options.vendoredModules);

  const bootstrap = fillSource(sketchpadBootstrapRaw, {
    __PH_CONTAINS_CENTER__: containsFragmentCenter.toString(),
    __PH_ERROR_TITLE__: JSON.stringify(SKETCHPAD_FRAGMENT_ERROR_TITLE),
    __PH_ERROR_HINT__: JSON.stringify(SKETCHPAD_FRAGMENT_ERROR_HINT),
    __PH_CHANNEL__: JSON.stringify(SKETCHPAD_CHANNEL),
    __PH_MAX_STATE_BYTES__: String(SKETCHPAD_MAX_STATE_VALUE_BYTES),
    __PH_READ_ONLY_STATE__: JSON.stringify(SHARED_FIELD_READ_ONLY_STATE),
    __PH_RESOLVE_EXTERNAL_URL__: resolveExternalAnchorUrl.toString(),
    __PH_ALLOWED_IMPORTS__: JSON.stringify([...SKETCHPAD_ALLOWED_IMPORTS]),
    __PH_CREATE_COMPILER__: createFragmentCompiler.toString(),
  });

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta http-equiv="x-dns-prefetch-control" content="off" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<script>
  var canvasImportMap = ${importMap};
  canvasImportMap.imports[${JSON.stringify(CANVAS_SDK_SPECIFIER)}] =
    URL.createObjectURL(new Blob([${JSON.stringify(SKETCHPAD_FRAME_SDK_MODULE_SOURCE)}], { type: "text/javascript" }));
  var canvasImportMapTag = document.createElement("script");
  canvasImportMapTag.type = "importmap";
  canvasImportMapTag.textContent = JSON.stringify(canvasImportMap);
  document.head.appendChild(canvasImportMapTag);
</script>
<script type="module" src="${moduleUrl(TAILWIND_URL)}"></script>
${TAILWIND_STYLE}
${FREEFORM_QUILL_CSS_URLS.map(
  (href) => `<link rel="stylesheet" href="${moduleUrl(href)}" />`,
).join("\n")}
<style>${sketchpadFrameRaw}</style>
</head>
<body>
<div id="world"></div>
<script type="module">${bootstrap}</script>
</body>
</html>`;
}

export function sketchpadFramePolicy(vendoredModules: boolean): string {
  const modules = vendoredModules
    ? `${SKETCHPAD_MODULE_SCHEME}:`
    : `${SKETCHPAD_TAILWIND_PREFIX} ${FREEFORM_ESM_HOST}`;
  return [
    "default-src 'none'",
    `script-src 'unsafe-inline' blob: ${modules}`,
    `style-src 'unsafe-inline' ${modules}`,
    `font-src data: ${modules}`,
    "img-src data: blob:",
    "media-src data: blob:",
    "worker-src blob:",
    "connect-src 'none'",
    "prefetch-src 'none'",
    "webrtc 'block'",
    "form-action 'none'",
    "base-uri 'none'",
    "object-src 'none'",
    "frame-src 'none'",
    "manifest-src 'none'",
  ].join("; ");
}

function fillSource(source: string, values: Record<string, string>): string {
  return source.replace(/__PH_[A-Za-z0-9_]+__/g, (token) => {
    const value = values[token];
    if (value === undefined)
      throw new Error(`Missing frame source value: ${token}`);
    return value;
  });
}
