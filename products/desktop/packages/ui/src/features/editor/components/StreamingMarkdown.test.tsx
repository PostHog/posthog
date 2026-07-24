import { StreamingMarkdown } from "@posthog/ui/features/editor/components/StreamingMarkdown";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/themeStore", () => ({
  useThemeStore: (selector: (state: { isDarkMode: boolean }) => unknown) =>
    selector({ isDarkMode: false }),
}));

vi.mock("@posthog/ui/utils/syntax-highlight", () => ({
  highlightSyntax: () => null,
}));

function renderInTheme(ui: ReactElement) {
  return render(<Theme>{ui}</Theme>);
}

describe("StreamingMarkdown", () => {
  it("renders prose before an open fence and the code as a box without a copy button", () => {
    renderInTheme(<StreamingMarkdown content={"Here:\n```ts\nconst a = 1;"} />);

    expect(screen.getByText("Here:")).toBeInTheDocument();
    expect(screen.getByText("const a = 1;")).toBeInTheDocument();
    // The interim box stays copy-button-free until the fence closes.
    expect(screen.queryByLabelText("Copy code")).toBeNull();
  });

  it("renders an open fence at the very start as a code box", () => {
    renderInTheme(<StreamingMarkdown content={"```ts\nconst a = 1;"} />);

    expect(screen.getByText("const a = 1;")).toBeInTheDocument();
    expect(screen.queryByLabelText("Copy code")).toBeNull();
  });

  it("renders fully completed markdown with no interim code box", () => {
    renderInTheme(<StreamingMarkdown content={"# Title\n\nAll done."} />);

    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("All done.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Copy code")).toBeNull();
  });
});
