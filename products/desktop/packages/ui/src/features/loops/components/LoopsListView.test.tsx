import type { LoopSchemas } from "@posthog/api-client/loops";
import { Theme } from "@radix-ui/themes";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoopsListViewPresentation } from "./LoopsListView";

vi.mock("./LoopBuilderComposer", () => ({
  LoopBuilderComposer: () => null,
}));
vi.mock("./LoopTemplatesSection", () => ({
  LoopTemplatesSection: () => null,
}));
vi.mock("./LoopRow", () => ({
  LoopRow: ({ loop }: { loop: LoopSchemas.Loop }) => <div>{loop.name}</div>,
}));

function loop(
  id: string,
  visibility: LoopSchemas.LoopVisibilityEnum,
): LoopSchemas.Loop {
  return {
    id,
    name: `${visibility} loop`,
    visibility,
  } as LoopSchemas.Loop;
}

function controlledPanel(tab: HTMLElement): HTMLElement {
  const panelId = tab.getAttribute("aria-controls");
  const panel = document.getElementById(panelId ?? "");
  if (!panel) throw new Error("Tab does not control a panel");
  return panel;
}

describe("LoopsListViewPresentation", () => {
  it("shows only the selected ownership tab", async () => {
    render(
      <Theme>
        <LoopsListViewPresentation
          loops={[loop("personal", "personal"), loop("team", "team")]}
          onStartBlank={vi.fn()}
          onStartFromTemplate={vi.fn()}
        />
      </Theme>,
    );

    const personalTab = screen.getByRole("tab", { name: "My loops (1)" });
    expect(
      within(controlledPanel(personalTab)).getByText("personal loop"),
    ).toBeVisible();
    expect(screen.queryByText("team loop")).not.toBeInTheDocument();

    const teamTab = screen.getByRole("tab", { name: "Team loops (1)" });
    await userEvent.click(teamTab);

    expect(teamTab).toHaveAttribute("aria-selected", "true");
    expect(
      within(controlledPanel(teamTab)).getByText("team loop"),
    ).toBeVisible();
    expect(controlledPanel(personalTab)).toHaveAttribute("inert");
  });
});
