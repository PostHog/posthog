// Mobile has no DOMParser, so this removes the meta tag at the string level
// rather than reusing the desktop DOM-based removal. The scan is attribute
// aware — a quoted ">" inside an attribute value does not end the tag, and
// http-equiv is read as a parsed attribute rather than matched as loose text —
// so it agrees with what an HTML tokenizer sees.

// Returns the index just past the ">" that closes the tag opened at `from`,
// skipping over quoted attribute values.
function tagEnd(html: string, from: number): number {
  let index = from;
  while (index < html.length) {
    const char = html[index];
    if (char === '"' || char === "'") {
      const closingQuote = html.indexOf(char, index + 1);
      // An unterminated quote swallows the rest of the document, exactly as a
      // tokenizer stuck in the attribute-value state would.
      if (closingQuote === -1) return html.length;
      index = closingQuote + 1;
      continue;
    }
    if (char === ">") return index + 1;
    index += 1;
  }
  return html.length;
}

const META_TAG = /<meta\b/gi;
const ATTRIBUTE = /([^\s/>=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]*)))?/g;

function isRefreshMeta(tag: string): boolean {
  ATTRIBUTE.lastIndex = "<meta".length;
  let attribute = ATTRIBUTE.exec(tag);
  while (attribute !== null) {
    const name = attribute[1].toLowerCase();
    const value = attribute[2] ?? attribute[3] ?? attribute[4] ?? "";
    if (name === "http-equiv" && value.trim().toLowerCase() === "refresh") {
      return true;
    }
    attribute = ATTRIBUTE.exec(tag);
  }
  return false;
}

export function removeAutomaticRedirects(html: string): string {
  META_TAG.lastIndex = 0;
  let kept = "";
  let copiedUpTo = 0;
  let stripped = false;
  let match = META_TAG.exec(html);
  while (match !== null) {
    const end = tagEnd(html, match.index + match[0].length);
    if (isRefreshMeta(html.slice(match.index, end))) {
      kept += html.slice(copiedUpTo, match.index);
      copiedUpTo = end;
      stripped = true;
    }
    META_TAG.lastIndex = end;
    match = META_TAG.exec(html);
  }
  return stripped ? kept + html.slice(copiedUpTo) : html;
}

// mediaCapturePermissionGrantType is an iOS-only prop. On Android
// react-native-webview's WebChromeClient grants a getUserMedia request whenever
// the host app already holds CAMERA or RECORD_AUDIO, which this app does for QR
// sign-in and voice input — so an artifact could otherwise reach the camera or
// microphone. Removing the entry points from the document is the only lever
// available without patching the library's native WebChromeClient, so treat it
// as defence in depth: a script that builds a fresh realm (an about:blank
// iframe, which frame-src 'none' does not cover) can still find an unpatched
// navigator. That gap cannot be closed from script — patching
// HTMLIFrameElement's contentWindow getter still leaves window[0], an
// unconfigurable WindowProxy index. Closing it properly means a native
// WebChromeClient whose onPermissionRequest denies RESOURCE_VIDEO_CAPTURE and
// RESOURCE_AUDIO_CAPTURE, i.e. a patch to react-native-webview, which affects
// every WebView in the app and so needs its own change.
const MEDIA_CAPTURE_GUARD = `<script>(function () {
  var hide = function (target, key) {
    try {
      Object.defineProperty(target, key, {
        value: undefined,
        writable: false,
        configurable: false,
      });
    } catch (error) {}
  };
  hide(navigator, "mediaDevices");
  hide(navigator, "getUserMedia");
  hide(navigator, "webkitGetUserMedia");
  hide(navigator, "mozGetUserMedia");
})();</script>`;

// Inserted after the doctype, which must stay first or the document drops into
// quirks mode. The parser hoists the script into <head>, ahead of the
// artifact's own markup, so it runs before any of the artifact's scripts.
export function denyMediaCapture(html: string): string {
  const doctype = html.match(/^\s*<!doctype[^>]*>/i);
  if (doctype) {
    return (
      html.slice(0, doctype[0].length) +
      MEDIA_CAPTURE_GUARD +
      html.slice(doctype[0].length)
    );
  }
  return MEDIA_CAPTURE_GUARD + html;
}
