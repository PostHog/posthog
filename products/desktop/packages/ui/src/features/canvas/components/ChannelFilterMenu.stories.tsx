import {
  type ChannelItemFilters,
  type ChannelItemGrouping,
  type ChannelItemSort,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DEFAULT_CHANNEL_ITEM_GROUPING,
  DEFAULT_CHANNEL_ITEM_SORT,
  hasActiveChannelItemFilters,
} from "@posthog/core/canvas/channelItems";
import { EditListItemAppearanceDialog } from "@posthog/ui/features/sidebar/components/EditListItemAppearanceDialog";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { ChannelFilterMenu } from "./ChannelFilterMenu";

/**
 * The menu owns nothing — the sessions list holds the filters — so the story
 * supplies the state the sidebar would, and the picks stick the way they do
 * there.
 */
function Harness({
  initialFilters,
  initialSort,
  sources,
  showCreatedBy,
  showRunFilters,
}: {
  initialFilters: ChannelItemFilters;
  initialSort: ChannelItemSort;
  sources: string[];
  showCreatedBy: boolean;
  showRunFilters: boolean;
}) {
  const [filters, setFilters] = useState(initialFilters);
  const [sort, setSort] = useState(initialSort);
  const [grouping, setGrouping] = useState<ChannelItemGrouping>(
    DEFAULT_CHANNEL_ITEM_GROUPING,
  );
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  return (
    <div className="flex justify-end p-2">
      <ChannelFilterMenu
        filters={filters}
        onFilterChange={(key, value) =>
          setFilters((current) => ({ ...current, [key]: value }))
        }
        onClearFilters={() => setFilters(DEFAULT_CHANNEL_ITEM_FILTERS)}
        sort={sort}
        onSortChange={setSort}
        grouping={grouping}
        onGroupingChange={setGrouping}
        onEditAppearance={() => setAppearanceOpen(true)}
        sources={sources}
        showCreatedBy={showCreatedBy}
        showRunFilters={showRunFilters}
        active={hasActiveChannelItemFilters(filters)}
      />
      {/* The list owns the dialog and the menu only asks for it — so the
          harness renders it too, the way the sidebar does. */}
      <EditListItemAppearanceDialog
        surface="space"
        open={appearanceOpen}
        onOpenChange={setAppearanceOpen}
      />
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Spaces/ChannelFilterMenu",
  component: Harness,
  args: {
    initialFilters: DEFAULT_CHANNEL_ITEM_FILTERS,
    initialSort: DEFAULT_CHANNEL_ITEM_SORT,
    sources: ["slack", "error_tracking", "support_queue"],
    showCreatedBy: true,
    showRunFilters: true,
  },
  decorators: [
    (Story) => (
      <div className="w-64 border border-border">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Harness>;

export const Default: Story = {};

/** A filter is on, so the button is lit and the menu offers a way out. */
export const Filtered: Story = {
  args: {
    initialFilters: {
      ...DEFAULT_CHANNEL_ITEM_FILTERS,
      attention: "needs_input",
      environment: "cloud",
    },
  },
};

/** The canvases tab: no run to filter on, and no metadata row to configure. */
export const CanvasesTab: Story = {
  args: { showRunFilters: false },
};

/** #me, where every session is yours: no "created by", and no filed sources. */
export const PersonalSpace: Story = {
  args: { showCreatedBy: false, sources: [] },
};
