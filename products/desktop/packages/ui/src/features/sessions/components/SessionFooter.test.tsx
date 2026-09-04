import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SessionFooter } from "./SessionFooter";

describe("SessionFooter", () => {
  it.each([
    ["compaction", { isCompacting: true }],
    ["conversation clearing", { isClearing: true }],
  ])("hides the generating footer during %s", (_label, state) => {
    render(
      <Theme>
        <SessionFooter
          isPromptPending
          promptStartedAt={Date.now()}
          lastGenerationDuration={null}
          {...state}
        />
      </Theme>,
    );

    expect(screen.queryByText(/Esc to stop/)).not.toBeInTheDocument();
  });

  it("shows the generating footer for a background Codex turn", () => {
    render(
      <Theme>
        <SessionFooter
          isPromptPending={false}
          isBackgroundTurnActive
          promptStartedAt={Date.now()}
          lastGenerationDuration={null}
        />
      </Theme>,
    );

    expect(screen.getByText(/Esc to stop/)).toBeInTheDocument();
  });
});
