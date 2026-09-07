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

import { AgentMessage } from "./AgentMessage";

const MERMAID_FENCE = "```mermaid\ngraph TD; A-->B\n```";

describe("AgentMessage", () => {
  it("renders mermaid fences as diagrams after streaming completes", async () => {
    render(<AgentMessage content={MERMAID_FENCE} />);

    expect(await screen.findByTestId("mermaid-svg")).toBeInTheDocument();
    expect(screen.queryByText("graph TD; A-->B")).toBeNull();
  });
});
