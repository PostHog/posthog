import type { LoopSchemas } from "@posthog/api-client/loops";
import type { UserBasic } from "@posthog/shared/domain-types";
import { Theme } from "@radix-ui/themes";
import { render, screen, waitFor, within } from "@testing-library/react";
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
  LoopRow: ({
    loop,
    creator,
  }: {
    loop: LoopSchemas.Loop;
    creator?: UserBasic;
  }) => (
    <div>
      {loop.name}
      {loop.visibility === "team" && creator ? ` by ${creator.email}` : null}
    </div>
  ),
}));

function loop(
  id: string,
  visibility: LoopSchemas.LoopVisibilityEnum,
  createdById = 1,
): LoopSchemas.Loop {
  return {
    id,
    name: `${visibility} loop`,
    visibility,
    created_by_id: createdById,
  } as LoopSchemas.Loop;
}

function controlledPanel(tab: HTMLElement): HTMLElement {
  const panelId = tab.getAttribute("aria-controls");
  const panel = document.getElementById(panelId ?? "");
  if (!panel) throw new Error("Tab does not control a panel");
  return panel;
}

describe("LoopsListViewPresentation", () => {
  it("does not render visibility groups while loops are loading", () => {
    render(
      <Theme>
        <LoopsListViewPresentation
          loops={[loop("mine-team", "team")]}
          isLoading
          onStartBlank={vi.fn()}
          onStartFromTemplate={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });

  // The triggers sit in the page header and the panels stay in the scrolling
  // body — one Tabs root spanning both, so switching has to keep working
  // across that split.
  it("groups loops by visibility regardless of their creator", async () => {
    const currentUser: UserBasic = {
      id: 1,
      uuid: "current-user",
      email: "current@example.com",
    };
    render(
      <Theme>
        <LoopsListViewPresentation
          loops={[
            loop("personal", "personal"),
            loop("mine-team", "team"),
            loop("teammate-team", "team", 2),
          ]}
          members={[currentUser]}
          onStartBlank={vi.fn()}
          onStartFromTemplate={vi.fn()}
        />
      </Theme>,
    );

    const personalTab = screen.getByRole("tab", { name: "My loops (1)" });
    expect(
      within(controlledPanel(personalTab)).getByText("personal loop"),
    ).toBeVisible();

    const teamTab = screen.getByRole("tab", { name: "Team loops (2)" });
    await userEvent.click(teamTab);

    expect(teamTab).toHaveAttribute("aria-selected", "true");
    expect(
      within(controlledPanel(teamTab)).getByText(
        "team loop by current@example.com",
      ),
    ).toBeVisible();
    expect(
      within(controlledPanel(teamTab)).getAllByText(/team loop/),
    ).toHaveLength(2);
    // The deselected panel is inert, then unmounts when its transition ends.
    await waitFor(() =>
      expect(screen.queryByText("personal loop")).not.toBeInTheDocument(),
    );
  });

  it("hides the header trigger strip while loops are loading", () => {
    render(
      <Theme>
        <LoopsListViewPresentation
          loops={[]}
          isLoading
          onStartBlank={vi.fn()}
          onStartFromTemplate={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });
});
