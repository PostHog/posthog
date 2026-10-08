import type { LoopSchemas } from "@posthog/api-client/loops";
import { Theme } from "@radix-ui/themes";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { LoopSpace } from "../loopScopes";
import { LoopsListViewPresentation } from "./LoopsListView";

vi.mock("./LoopBuilderComposer", () => ({
  LoopBuilderComposer: () => null,
}));
vi.mock("./LoopTemplatesSection", () => ({
  LoopTemplatesSection: () => null,
}));
vi.mock("../hooks/useLoopMutations", () => ({
  useUpdateLoop: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@tanstack/react-router", () => ({
  Link: ({
    children,
    params,
    to,
  }: {
    children: React.ReactNode;
    params?: { channelId?: string; loopId?: string };
    to: string;
  }) => (
    <a
      href={to
        .replace("$channelId", params?.channelId ?? "")
        .replace("$loopId", params?.loopId ?? "")}
    >
      {children}
    </a>
  ),
}));

function loop(
  id: string,
  name: string,
  overrides: Partial<LoopSchemas.Loop> & {
    space?: { channel_id: string; name: string } | null;
  } = {},
): LoopSchemas.Loop {
  const { space = null, ...rest } = overrides;
  return {
    id,
    name,
    description: "",
    visibility: "team",
    enabled: true,
    disabled_reason: null,
    created_by_id: 1,
    triggers: [],
    consecutive_failures: 0,
    last_run_at: null,
    last_run_status: null,
    context_target: space
      ? {
          ...space,
          outputs: {
            post_to_feed: true,
            update_context: false,
            canvas_id: null,
          },
        }
      : null,
    ...rest,
  } as LoopSchemas.Loop;
}

const GROWTH: LoopSpace = {
  id: "space-growth",
  name: "growth",
  channelType: "public",
};

async function pick(filterLabel: string, option: RegExp): Promise<void> {
  await userEvent.click(screen.getByRole("button", { name: filterLabel }));
  await userEvent.click(
    await screen.findByRole("menuitemradio", { name: option }),
  );
}

function tableRows(): HTMLElement[] {
  return within(screen.getByRole("table")).getAllByRole("row").slice(1);
}

describe("LoopsListViewPresentation", () => {
  it("renders no table while loops are loading", () => {
    render(
      <Theme>
        <LoopsListViewPresentation
          loops={[loop("a", "Global one")]}
          isLoading
          onStartBlank={vi.fn()}
          onStartFromTemplate={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("lists every loop with its space", async () => {
    render(
      <Theme>
        <LoopsListViewPresentation
          loops={[
            loop("a", "Global one"),
            loop("b", "Growth digest", {
              space: { channel_id: GROWTH.id, name: "growth" },
            }),
            loop("c", "Orphan watch", {
              space: { channel_id: "gone", name: "me" },
            }),
          ]}
          spaces={[GROWTH]}
          onStartBlank={vi.fn()}
          onStartFromTemplate={vi.fn()}
        />
      </Theme>,
    );

    await pick("Filter by scope", /^All loops/);
    expect(tableRows()).toHaveLength(3);
    const growthRow = screen.getByRole("row", { name: /Growth digest/ });
    expect(
      within(growthRow).getByRole("link", { name: /growth/ }),
    ).toHaveAttribute("href", "/spaces/space-growth/loops");
    const orphanRow = screen.getByRole("row", { name: /Orphan watch/ });
    expect(
      within(orphanRow).getByText("Teammate's personal space"),
    ).toBeVisible();
    expect(
      within(orphanRow).queryByRole("link", { name: /personal/ }),
    ).toBeNull();

    expect(
      screen.getByText("3 active · 1 global · 2 in 2 spaces"),
    ).toBeVisible();
    expect(
      screen.getByText("3 active · 1 global · 2 in 2 spaces"),
    ).toBeVisible();
  });

  it("narrows the table by scope, visibility, search and paused state", async () => {
    render(
      <Theme>
        <LoopsListViewPresentation
          loops={[
            loop("a", "Global one"),
            loop("b", "Growth digest", {
              space: { channel_id: GROWTH.id, name: "growth" },
            }),
            loop("c", "My reminder", {
              visibility: "personal",
              enabled: false,
            }),
          ]}
          spaces={[GROWTH]}
          onStartBlank={vi.fn()}
          onStartFromTemplate={vi.fn()}
        />
      </Theme>,
    );

    expect(tableRows()).toHaveLength(2);
    expect(screen.queryByText("Growth digest")).not.toBeInTheDocument();

    await pick("Filter by visibility", /^Personal loops/);
    expect(tableRows()).toHaveLength(1);
    expect(screen.getByText("My reminder")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Hide paused" }));
    expect(
      screen.getByText("No loops match the current filters."),
    ).toBeVisible();

    await pick("Filter by scope", /^All loops/);
    await pick("Filter by visibility", /^Team and personal/);
    await userEvent.click(screen.getByRole("button", { name: /Hide paused/ }));
    await userEvent.type(screen.getByPlaceholderText("Search loops"), "growth");
    expect(tableRows()).toHaveLength(1);
    expect(screen.getByText("Growth digest")).toBeVisible();
  });
});
