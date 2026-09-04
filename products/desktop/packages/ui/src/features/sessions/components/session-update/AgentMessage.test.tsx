import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async () => ({
      svg: '<svg data-testid="mermaid-svg"></svg>',
    })),
  },
}));

vi.mock("@posthog/ui/shell/themeStore", () => ({
  useThemeStore: (selector: (state: { isDarkMode: boolean }) => unknown) =>
    selector({ isDarkMode: false }),
}));

vi.mock("../../../sidebar/useCwd", () => ({
  useCwd: () => undefined,
}));

import { AgentMessage } from "./AgentMessage";

const MERMAID_FENCE = "```mermaid\ngraph TD; A-->B\n```";

describe("AgentMessage", () => {
  it("renders mermaid fences as diagrams after streaming completes", async () => {
    render(<AgentMessage content={MERMAID_FENCE} />);

    expect(await screen.findByTestId("mermaid-svg")).toBeInTheDocument();
    expect(screen.queryByText("graph TD; A-->B")).toBeNull();
  });

  it("renders inline file references as selectable text, not buttons", () => {
    render(<AgentMessage content="See `src/app/AgentMessage.tsx:12` here." />);

    const chip = screen.getByText("AgentMessage.tsx:12");
    // Chromium drops <button> text from document selections, so a native
    // <button> chip would vanish from text copied out of chat output.
    expect(chip.closest("button")).toBeNull();
    expect(chip.tagName).toBe("SPAN");
  });
});
