import { DropdownMenu, DropdownMenuContent } from "@posthog/quill";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelSelectList } from "./ModelSelectList";

describe("model picker rows", () => {
  it("keeps the list rendering when the price table has no row for a model", () => {
    render(
      <DropdownMenu open>
        <DropdownMenuContent>
          <ModelSelectList
            options={[
              { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
              { value: "gpt-5.99", name: "GPT-5.99" },
            ]}
            currentValue="claude-sonnet-5"
            onSelect={() => {}}
          />
        </DropdownMenuContent>
      </DropdownMenu>,
    );

    expect(screen.getByText("Claude Sonnet 5")).toBeInTheDocument();
    expect(screen.getByText("GPT-5.99")).toBeInTheDocument();
    // Only the priced row keeps a cost chip.
    expect(screen.getAllByTitle(/Cost per token/)).toHaveLength(1);
  });
});
