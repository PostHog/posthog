import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { MarkdownText } from "./MarkdownText";

vi.mock("@/features/auth", () => ({
  useAuthStore: () => null,
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 9: "#888888", 11: "#444444", 12: "#111111" },
    accent: { 11: "#ff5500" },
  }),
}));

vi.mock("./CopyButton", () => ({
  CopyButton: (props: Record<string, unknown>) =>
    createElement("CopyButton", props),
}));

vi.mock("./MarkdownImage", () => ({
  MarkdownImage: (props: Record<string, unknown>) =>
    createElement("MarkdownImage", props),
}));

vi.mock("./GithubRefChip", () => ({
  GithubRefChip: (props: Record<string, unknown>) =>
    createElement("GithubRefChip", props),
}));

vi.mock("./FileRefChip", () => ({
  FileRefChip: (props: Record<string, unknown>) =>
    createElement("FileRefChip", props),
}));

vi.mock("./PostHogRefChip", () => ({
  PostHogRefChip: (props: Record<string, unknown>) =>
    createElement("PostHogRefChip", props),
}));

function render(content: string) {
  let renderer!: ReturnType<typeof create>;
  act(() => {
    renderer = create(createElement(MarkdownText, { content }));
  });
  return renderer;
}

function chips(renderer: ReturnType<typeof create>, type: string) {
  return renderer.root
    .findAll((node) => String(node.type) === type)
    .map((node) => node.props);
}

/** Every string leaf of the rendered tree, in order. */
function textContent(renderer: ReturnType<typeof create>): string {
  const parts: string[] = [];
  const walk = (node: unknown): void => {
    if (typeof node === "string") {
      parts.push(node);
    } else if (Array.isArray(node)) {
      for (const child of node) walk(child);
    } else if (node && typeof node === "object" && "children" in node) {
      walk((node as { children: unknown }).children);
    }
  };
  walk(renderer.toJSON());
  return parts.join("");
}

describe("MarkdownText pseudo-tags", () => {
  it("renders a file tag as a non-tappable file chip", () => {
    const renderer = render(
      'Look at <file path="/var/folders/xy/T/report.md" /> please',
    );

    expect(chips(renderer, "FileRefChip")).toEqual([
      { label: "T/report.md", fromDesktop: true },
    ]);
    expect(textContent(renderer)).not.toContain("<file path");
  });

  it("renders a github_pr tag as a tappable PR chip", () => {
    const renderer = render(
      'Review <github_pr number="123" title="Ship it" url="https://github.com/org/repo/pull/123" />',
    );

    expect(chips(renderer, "GithubRefChip")).toEqual([
      {
        href: "https://github.com/org/repo/pull/123",
        kind: "pr",
        label: "#123 - Ship it",
      },
    ]);
    expect(textContent(renderer)).not.toContain("<github_pr");
  });

  it("keeps markdown around the tags working", () => {
    const renderer = render(
      '**Bold** and <file path="src/a.ts" /> and *italic*',
    );

    expect(chips(renderer, "FileRefChip")).toHaveLength(1);
    const rendered = textContent(renderer);
    expect(rendered).toContain("Bold");
    expect(rendered).toContain("italic");
    expect(rendered).not.toContain("**Bold**");
  });

  it("renders tags across a multiline description", () => {
    const renderer = render(
      [
        "Compare:",
        "",
        '- <file path="/Users/vasco/repo/src/a.ts" />',
        '- <github_pr number="9" title="" url="https://github.com/org/repo/pull/9" />',
      ].join("\n"),
    );

    expect(chips(renderer, "FileRefChip")).toHaveLength(1);
    expect(chips(renderer, "GithubRefChip")).toEqual([
      {
        href: "https://github.com/org/repo/pull/9",
        kind: "pr",
        label: "#9",
      },
    ]);
  });

  it("leaves tag-like text inside a code block alone", () => {
    const renderer = render('```\n<file path="src/a.ts" />\n```');

    expect(chips(renderer, "FileRefChip")).toHaveLength(0);
    expect(textContent(renderer)).toContain("<file path=");
  });

  it("leaves a malformed tag as raw text", () => {
    const renderer = render('Look at <file path="src/a.ts"> please');

    expect(chips(renderer, "FileRefChip")).toHaveLength(0);
    expect(textContent(renderer)).toContain('<file path="src/a.ts">');
  });
});
