import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({
    members: [
      {
        id: 1,
        uuid: "uuid-shy",
        email: "shy@example.com",
        first_name: "Shy",
        last_name: "Levi",
      },
      {
        id: 2,
        uuid: "uuid-moshe",
        email: "moshe@example.com",
        first_name: "Moshe",
        last_name: "Katz",
      },
      {
        id: 3,
        uuid: "uuid-alex-one",
        email: "alex@example.com",
        first_name: "Alex",
        last_name: "One",
      },
      {
        id: 4,
        uuid: "uuid-alex-two",
        email: "alex@example.org",
        first_name: "Alex",
        last_name: "Two",
      },
    ],
    isLoading: false,
    isError: false,
    isComplete: true,
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [
      {
        id: "space-app",
        name: "desktop app",
        channelType: "public",
        starred: false,
        repositories: ["example-org/webapp"],
        createdBy: null,
      },
    ],
    isLoading: false,
  }),
}));

import { FeedQueryHighlight, FeedQueryInput } from "./FeedQueryInput";

function Harness({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <Theme>
      <FeedQueryInput aria-label="Query" value={value} onChange={setValue} />
      <output>{value}</output>
    </Theme>
  );
}

describe("FeedQueryInput", () => {
  it("completes a key, then a teammate, into one token", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox");

    await user.type(input, "cre");
    // The bolded match prefix splits the label across spans, and accessible
    // name computation joins them with a space, so match loosely.
    await user.click(screen.getByRole("option", { name: /ated-by:/ }));
    // The key completion keeps the list open on its values.
    await user.type(input, "sh");
    await user.click(screen.getByRole("option", { name: /shy@example\.com/ }));

    expect(screen.getByRole("status")).toHaveTextContent("created-by:shy");
  });

  it("uses full emails to distinguish teammates with matching names", async () => {
    const user = userEvent.setup();
    render(<Harness initial="created-by:alex" />);
    const input = screen.getByRole("combobox");

    await user.click(input);
    await user.click(screen.getByRole("option", { name: /alex@example\.org/ }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "created-by:alex@example.org",
    );
  });

  it("keeps the negation prefix through a completion", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox");

    await user.type(input, "-sta");
    await user.keyboard("{Enter}");
    await user.keyboard("{Enter}");

    expect(screen.getByRole("status").textContent).toMatch(/^-status:/);
  });

  it("keeps a not: value negation through a completion", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox");

    await user.type(input, "status:not:f");
    await user.keyboard("{Enter}");

    // Completing the value must not drop `not:` and flip the filter to positive.
    expect(screen.getByRole("status")).toHaveTextContent("status:not:failed");
  });

  it("does not submit while IME text composition is active", () => {
    const onSubmit = vi.fn();
    render(
      <Theme>
        <FeedQueryInput
          aria-label="Query"
          value="billing"
          onChange={vi.fn()}
          onSubmit={onSubmit}
        />
      </Theme>,
    );

    fireEvent.keyDown(screen.getByRole("combobox"), {
      key: "Enter",
      isComposing: true,
    });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("links keyboard selection to the active suggestion", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox");

    await user.type(input, "s");
    const listbox = screen.getByRole("listbox", {
      name: "Query suggestions",
    });
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-controls", listbox.id);

    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      screen.getAllByRole("option")[1].id,
    );
  });

  it("quotes a suggested value that carries spaces", async () => {
    const user = userEvent.setup();
    render(<Harness initial="space:" />);
    const input = screen.getByRole("combobox");

    await user.click(input);
    await user.click(screen.getByRole("option", { name: "desktop app" }));

    expect(screen.getByRole("status")).toHaveTextContent('space:"desktop app"');
  });
});

describe("FeedQueryHighlight", () => {
  // The editor overlays this on a transparent input, so any drift between the
  // rendered text and the raw string shears the caret off the colored glyphs.
  it("round-trips the query text exactly", () => {
    const query = ' fix  space:"desktop app" -status:failed x ';
    const { container } = render(
      <Theme>
        <FeedQueryHighlight query={query} />
      </Theme>,
    );
    expect(container.textContent).toBe(query);
  });

  it("marks invalid values with the wavy underline", () => {
    const { container } = render(
      <Theme>
        <FeedQueryHighlight query="status:sideways" />
      </Theme>,
    );
    expect(container.querySelector(".decoration-wavy")).toBeTruthy();
  });

  it("renders a now-supported ci value without warning marks", () => {
    const { container } = render(
      <Theme>
        <FeedQueryHighlight query="ci:red" />
      </Theme>,
    );
    expect(container.querySelector(".decoration-dotted")).toBeNull();
    expect(container.querySelector(".decoration-wavy")).toBeNull();
  });
});
