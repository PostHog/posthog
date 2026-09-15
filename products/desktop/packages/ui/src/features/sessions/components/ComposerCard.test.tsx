import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ComposerCard } from "./ComposerCard";

describe("ComposerCard", () => {
  it("keeps the controls reachable while nothing is docked above the input", () => {
    render(
      <ComposerCard
        controls={<button type="button">Queued messages</button>}
        controlsEnd={<button type="button">View plan</button>}
      >
        <textarea aria-label="Message" />
      </ComposerCard>,
    );

    expect(screen.getByText("Queued messages").closest("[inert]")).toBeNull();
    expect(screen.getByText("View plan").closest("[inert]")).toBeNull();
  });

  it("makes the controls inert while a panel is docked above the input", () => {
    render(
      <ComposerCard
        panel={<div>Implementation plan</div>}
        controls={<button type="button">Queued messages</button>}
      >
        <textarea aria-label="Message" />
      </ComposerCard>,
    );

    expect(screen.getByText("Implementation plan")).toBeTruthy();
    // The row animates out rather than unmounting, so it has to be taken out
    // of the tab order by hand.
    expect(
      screen.getByText("Queued messages").closest("[inert]"),
    ).not.toBeNull();
    expect(screen.getByLabelText("Message").closest("[inert]")).toBeNull();
  });
});
