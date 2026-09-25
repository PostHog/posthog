import {
  type ChannelItemFilters,
  type ChannelItemGrouping,
  type ChannelItemSort,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DEFAULT_CHANNEL_ITEM_GROUPING,
  DEFAULT_CHANNEL_ITEM_SORT,
  DESKTOP_SOURCE,
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
  defaultFilters,
  initialSort,
  sources,
  showCreatedBy,
  showRunFilters,
}: {
  initialFilters: ChannelItemFilters;
  defaultFilters: ChannelItemFilters;
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
        onClearFilters={() => setFilters(defaultFilters)}
        defaultFilters={defaultFilters}
        sort={sort}
        onSortChange={setSort}
        grouping={grouping}
        onGroupingChange={setGrouping}
        onEditAppearance={() => setAppearanceOpen(true)}
        sources={sources}
        showCreatedBy={showCreatedBy}
        showRunFilters={showRunFilters}
        active={hasActiveChannelItemFilters(filters, defaultFilters)}
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
    defaultFilters: DEFAULT_CHANNEL_ITEM_FILTERS,
    initialSort: DEFAULT_CHANNEL_ITEM_SORT,
    sources: ["posthog_ai", "slack", "error_tracking", "support_queue"],
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

export const DesktopDefault: Story = {
  args: {
    initialFilters: {
      ...DEFAULT_CHANNEL_ITEM_FILTERS,
      sources: [DESKTOP_SOURCE],
    },
    defaultFilters: {
      ...DEFAULT_CHANNEL_ITEM_FILTERS,
      sources: [DESKTOP_SOURCE],
    },
  },
};

export const SeveralSources: Story = {
  args: {
    initialFilters: {
      ...DEFAULT_CHANNEL_ITEM_FILTERS,
      sources: [DESKTOP_SOURCE, "slack"],
    },
    defaultFilters: {
      ...DEFAULT_CHANNEL_ITEM_FILTERS,
      sources: [DESKTOP_SOURCE],
    },
  },
};

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
