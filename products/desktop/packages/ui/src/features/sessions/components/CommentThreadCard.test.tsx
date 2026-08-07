import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarkdownRenderer } from "../../editor/components/MarkdownRenderer";
import {
  githubCommentComponents,
  isGitHubHostedImage,
} from "./CommentThreadCard";

describe("GitHub comment images", () => {
  it.each([
    "https://user-images.githubusercontent.com/1/example.png",
    "https://private-user-images.githubusercontent.com/1/example.png",
    "https://github.com/user-attachments/assets/12345678-1234-1234-1234-123456789abc",
  ])("allows GitHub-hosted image %s", (source) => {
    expect(isGitHubHostedImage(source)).toBe(true);
  });

  it.each([
    "http://user-images.githubusercontent.com/1/example.png",
    "https://github.com.example.com/user-attachments/assets/example",
    "https://example.com/tracking.png",
    "http://127.0.0.1/internal.png",
    "data:image/png;base64,aW1hZ2U=",
  ])("blocks non-GitHub image %s", (source) => {
    expect(isGitHubHostedImage(source)).toBe(false);
  });

  it("renders only GitHub-hosted images from comment markdown", () => {
    const html = renderToStaticMarkup(
      <MarkdownRenderer
        content={[
          "![GitHub image](https://user-images.githubusercontent.com/1/example.png)",
          "![External image](https://example.com/tracking.png)",
        ].join("\n\n")}
        componentsOverride={githubCommentComponents}
      />,
    );

    expect(html).toContain("user-images.githubusercontent.com/1/example.png");
    expect(html).not.toContain("example.com/tracking.png");
  });
});
