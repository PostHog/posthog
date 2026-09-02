import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PiQueuedMessagesDock } from "./PiQueuedMessagesDock";

describe("PiQueuedMessagesDock", () => {
  it("renders the single native queued message with ACP-style actions", () => {
    const onEdit = vi.fn();
    const onRemove = vi.fn();

    render(
      <Theme>
        <PiQueuedMessagesDock
          queue={{ steering: [], followUp: ["then summarize"] }}
          onEdit={onEdit}
          onRemove={onRemove}
        />
      </Theme>,
    );

    expect(screen.getByText("then summarize")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Edit queued message" }),
    );
    expect(onEdit).toHaveBeenCalledOnce();

    fireEvent.click(
      screen.getByRole("button", { name: "Discard queued message" }),
    );
    expect(onRemove).toHaveBeenCalledOnce();
  });

  it("preserves legacy multi-message queues behind one edit action", () => {
    render(
      <Theme>
        <PiQueuedMessagesDock
          queue={{
            steering: ["first", "second"],
            followUp: ["third"],
          }}
          onEdit={vi.fn()}
          onRemove={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.getByText("first")).toBeInTheDocument();
    expect(screen.getByText("second")).toBeInTheDocument();
    expect(screen.getByText("third")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Discard queued message" }),
    ).not.toBeInTheDocument();
  });

  it("does not render an empty queue", () => {
    const { container } = render(
      <PiQueuedMessagesDock
        queue={{ steering: [], followUp: [] }}
        onEdit={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
