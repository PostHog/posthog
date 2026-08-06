import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect } from "react";
import { useInboxSignalsFilterStore } from "../stores/inboxSignalsFilterStore";
import { InboxSearchFilterBar } from "./InboxSearchFilterBar";

function SetFilterState({
  children,
  state,
}: {
  children: React.ReactNode;
  state: Partial<
    Pick<
      ReturnType<typeof useInboxSignalsFilterStore.getState>,
      "searchQuery" | "sourceProductFilter" | "priorityFilter"
    >
  >;
}) {
  useEffect(() => {
    useInboxSignalsFilterStore.setState({
      searchQuery: "",
      sortField: "priority",
      sortDirection: "asc",
      sourceProductFilter: [],
      priorityFilter: [],
      ...state,
    });
  }, [state]);
  return <>{children}</>;
}

const meta: Meta<typeof InboxSearchFilterBar> = {
  title: "Inbox/InboxSearchFilterBar",
  component: InboxSearchFilterBar,
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 896, margin: "2rem auto", padding: "0 1rem" }}>
        <Story />
      </div>
    ),
  ],
  args: {
    onRefresh: () => {},
  },
};
export default meta;
type Story = StoryObj<typeof InboxSearchFilterBar>;

/** All filters at rest: quiet, borderless chips showing their category. */
export const Quiet: Story = {
  decorators: [
    (Story) => (
      <SetFilterState state={{}}>
        <Story />
      </SetFilterState>
    ),
  ],
};

/** Active filters gain a border and show their selected value. */
export const WithActiveFilters: Story = {
  decorators: [
    (Story) => (
      <SetFilterState
        state={{
          sourceProductFilter: ["error_tracking"],
          priorityFilter: ["P0", "P1"],
        }}
      >
        <Story />
      </SetFilterState>
    ),
  ],
};

export const Refreshing: Story = {
  args: { refreshing: true },
  decorators: [
    (Story) => (
      <SetFilterState state={{}}>
        <Story />
      </SetFilterState>
    ),
  ],
};
