import type { Components } from "react-markdown";

const GITHUB_IMAGE_HOSTS = new Set([
  "avatars.githubusercontent.com",
  "camo.githubusercontent.com",
  "github.githubassets.com",
  "private-user-images.githubusercontent.com",
  "raw.githubusercontent.com",
  "user-images.githubusercontent.com",
]);

export function isGitHubHostedImage(source: string | undefined): boolean {
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

export const githubCommentComponents: Partial<Components> = {
  img: ({ src, alt }) =>
    isGitHubHostedImage(src) ? <img src={src} alt={alt ?? ""} /> : null,
};
