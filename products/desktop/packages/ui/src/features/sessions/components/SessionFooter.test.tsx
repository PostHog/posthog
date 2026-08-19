import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SessionFooter } from "./SessionFooter";

describe("SessionFooter", () => {
  it.each([
    ["compaction", { isCompacting: true }],
    ["conversation clearing", { isClearing: true }],
  ])("keeps the generating footer visible during %s", (_label, state) => {
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

    expect(screen.getByText(/Esc to stop/)).toBeInTheDocument();
  });
});
