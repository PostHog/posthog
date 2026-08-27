import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LoopsEmptyState } from "./LoopsEmptyState";

describe("LoopsEmptyState", () => {
  it.each([
    { contextName: undefined, heading: "Create your first loop" },
    { contextName: "general", heading: "Create a loop for #general" },
  ])(
    'shows "$heading" when contextName is $contextName',
    ({ contextName, heading }) => {
      render(
        <Theme>
          <LoopsEmptyState contextName={contextName} />
        </Theme>,
      );

      expect(screen.getByText(heading)).toBeInTheDocument();
    },
  );
});
