// The packaged renderer is loaded from a file:// URL, and Chromium never
// sends a Referer header from file:// documents. YouTube rejects
// referrer-less embed requests with player error 153 ("Video player
// configuration error"), which breaks the Brainrot cell in production while
// dev (served from the Vite http origin) keeps working. Injecting a Referer
// for embed traffic gives YouTube the referrer information it requires.

interface BeforeSendHeadersDetails {
  requestHeaders: Record<string, string>;
}

interface BeforeSendHeadersResponse {
  requestHeaders?: Record<string, string>;
}

export interface HeaderRewritingWebRequest {
  onBeforeSendHeaders(
    filter: { urls: string[] },
    listener: (
      details: BeforeSendHeadersDetails,
      callback: (response: BeforeSendHeadersResponse) => void,
    ) => void,
  ): void;
}

export const YOUTUBE_EMBED_REFERRER = "https://posthog.com/";

// Only the embed document itself needs the rewrite: subresources requested
// from inside the iframe already carry the iframe's https origin as referrer.
const YOUTUBE_EMBED_URL_PATTERNS = ["https://www.youtube-nocookie.com/*"];

export function withYoutubeEmbedReferrer(
  requestHeaders: Record<string, string>,
): Record<string, string> | null {
  const hasReferer = Object.keys(requestHeaders).some(
    (name) => name.toLowerCase() === "referer",
  );
  if (hasReferer) return null;
  return { ...requestHeaders, Referer: YOUTUBE_EMBED_REFERRER };
}

export function installYoutubeEmbedReferrer(
  webRequest: HeaderRewritingWebRequest,
): void {
  webRequest.onBeforeSendHeaders(
    { urls: YOUTUBE_EMBED_URL_PATTERNS },
    (details, callback) => {
      const rewritten = withYoutubeEmbedReferrer(details.requestHeaders);
      callback(rewritten ? { requestHeaders: rewritten } : {});
    },
  );
}
