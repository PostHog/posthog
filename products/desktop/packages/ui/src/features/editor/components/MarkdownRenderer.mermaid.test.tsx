import { MarkdownDocumentPreview } from "@posthog/ui/features/code-editor/components/MarkdownDocumentPreview";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { render, screen } from "@testing-library/react";
import mermaid from "mermaid";
import { describe, expect, it, vi } from "vitest";

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async (_id: string, code: string) => {
      if (code.includes("broken")) {
        throw new Error("Parse error on line 1");
      }
      return { svg: '<svg data-testid="mermaid-svg"></svg>' };
    }),
  },
}));

vi.mock("@posthog/ui/shell/themeStore", () => ({
  useThemeStore: (selector: (state: { isDarkMode: boolean }) => unknown) =>
    selector({ isDarkMode: false }),
}));

vi.mock("@posthog/ui/utils/syntax-highlight", () => ({
  highlightSyntax: () => null,
}));

const MERMAID_FENCE = "```mermaid\ngraph TD; A-->B\n```";

describe("mermaid fences in markdown", () => {
  it.each([
    [
      "MarkdownRenderer",
      (content: string) => <MarkdownRenderer content={content} />,
    ],
    [
      "MarkdownDocumentPreview",
      (content: string) => <MarkdownDocumentPreview content={content} />,
    ],
  ])("%s renders a mermaid fence as a diagram", async (_name, make) => {
    render(make(MERMAID_FENCE));

    expect(await screen.findByTestId("mermaid-svg")).toBeInTheDocument();
    expect(screen.queryByText("graph TD; A-->B")).toBeNull();
    expect(screen.queryByLabelText("Copy code")).toBeNull();
  });

  it("keeps other fences as code blocks", () => {
    render(<MarkdownRenderer content={"```ts\nconst a = 1;\n```"} />);

    expect(screen.getByText("const a = 1;")).toBeInTheDocument();
    expect(screen.getByLabelText("Copy code")).toBeInTheDocument();
    expect(screen.queryByTestId("mermaid-loading")).toBeNull();
  });

  it("shows the source and the parse error when the diagram is invalid", async () => {
    render(<MarkdownRenderer content={"```mermaid\ngraph TD; broken\n```"} />);

    expect(
      await screen.findByText(/Couldn't render this Mermaid diagram/),
    ).toHaveTextContent("Parse error on line 1");
    expect(screen.getByText("graph TD; broken")).toBeInTheDocument();
  });

  it.each([["img"], ["IMG"], ["'img'"]])(
    "never hands mermaid an image node that points at a remote URL (%s)",
    async (key) => {
      const remoteImage = `\`\`\`mermaid\nflowchart TD\n  A@{ ${key}: "http://127.0.0.1:9000/probe.png" }\n\`\`\``;
      render(<MarkdownRenderer content={remoteImage} />);

      expect(
        await screen.findByText(/Couldn't render this Mermaid diagram/),
      ).toHaveTextContent("image nodes can't load remote URLs");
      expect(mermaid.render).not.toHaveBeenCalledWith(
        expect.anything(),
        expect.stringContaining("127.0.0.1"),
      );
    },
  );

  it("keeps caller overrides in the document preview", () => {
    render(
      <MarkdownDocumentPreview
        content="See [docs](https://example.com)"
        components={{ a: ({ children }) => <span>override:{children}</span> }}
      />,
    );

    expect(screen.getByText("override:docs")).toBeInTheDocument();
  });
});
