import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { githubCommentComponents } from "./githubCommentImages";
import { MarkdownRenderer } from "./MarkdownRenderer";

vi.mock("@posthog/ui/shell/cachedImageUrl", () => ({
  cachedImageUrl: (remoteUrl: string) =>
    `posthog-cache://images/?src=${encodeURIComponent(remoteUrl)}`,
}));

const SOURCE = "https://user-images.githubusercontent.com/1/example.png";

describe("githubCommentComponents", () => {
  it("falls back to the origin when the cache declines the image", () => {
    render(
      <MarkdownRenderer
        content={`![Screenshot](${SOURCE})`}
        componentsOverride={githubCommentComponents}
      />,
    );

    const image = screen.getByAltText("Screenshot");
    expect(image).toHaveAttribute(
      "src",
      expect.stringContaining("posthog-cache://"),
    );

    fireEvent.error(image);

    expect(screen.getByAltText("Screenshot")).toHaveAttribute("src", SOURCE);
  });
});
