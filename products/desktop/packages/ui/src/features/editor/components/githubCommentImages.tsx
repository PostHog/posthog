import { cachedImageUrl } from "@posthog/ui/shell/cachedImageUrl";
import { useState } from "react";
import type { Components } from "react-markdown";

const GITHUB_IMAGE_HOSTS = new Set([
  "avatars.githubusercontent.com",
  "camo.githubusercontent.com",
  "github.githubassets.com",
  "private-user-images.githubusercontent.com",
  "raw.githubusercontent.com",
  "user-images.githubusercontent.com",
]);

export function isGitHubHostedImage(
  source: string | undefined,
): source is string {
  if (!source) return false;

  try {
    const url = new URL(source);
    return (
      url.protocol === "https:" &&
      (GITHUB_IMAGE_HOSTS.has(url.hostname) ||
        (url.hostname === "github.com" &&
          url.pathname.startsWith("/user-attachments/assets/")))
    );
  } catch {
    return false;
  }
}

/**
 * A comment image, read from the disk cache with the origin as a fallback.
 *
 * The cache answers 404 for anything it declines to hold, and a screenshot or
 * a screen-recording GIF often passes its size limit. GitHub serves those
 * fine, so a decline must not leave the reader with a broken image.
 */
function CommentImage({ src, alt }: { src: string; alt: string }) {
  const [declinedSrc, setDeclinedSrc] = useState<string | null>(null);

  return (
    <img
      src={declinedSrc === src ? src : cachedImageUrl(src)}
      alt={alt}
      onError={() => setDeclinedSrc(src)}
    />
  );
}

export const githubCommentComponents: Partial<Components> = {
  img: ({ src, alt }) =>
    isGitHubHostedImage(src) ? (
      <CommentImage src={src} alt={alt ?? ""} />
    ) : null,
};
