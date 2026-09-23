import {
  Autocomplete,
  AutocompleteList,
  TooltipProvider,
} from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { ChannelItemPreviewCardProvider } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import { ChannelSection } from "@posthog/ui/features/canvas/components/ChannelsList";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import type { Meta, StoryObj } from "@storybook/react-vite";

const emma: UserBasic = {
  id: 1,
  uuid: "user-emma",
  email: "emma@example.com",
  first_name: "Emma",
  last_name: "Ruiz",
};

function channel(overrides: Partial<Channel> & { name: string }): Channel {
  return {
    id: `channel-${overrides.name}`,
    channelType: "public",
    starred: true,
    repositories: [],
    createdBy: emma,
    ...overrides,
  };
}

// One row per combination of trailing marks, with names short to long, so the
// dots either make one column down the list or they do not.
const ROWS: {
  channel: Channel;
  unreadSessions?: number;
  blockedSessions?: number;
  hotkeySlot?: number;
}[] = [
  {
    channel: channel({ name: "general", systemRole: "general" }),
    hotkeySlot: 1,
  },
  { channel: channel({ name: "hedgebox-growth" }), unreadSessions: 3 },
  {
    channel: channel({ name: "web" }),
    unreadSessions: 1,
    blockedSessions: 2,
    hotkeySlot: 2,
  },
  {
    channel: channel({ name: "platform-infrastructure" }),
    unreadSessions: 4,
  },
  { channel: channel({ name: "test" }) },
];

const meta: Meta<typeof ChannelSection> = {
  title: "Spaces/ChannelsList",
  component: ChannelSection,
  decorators: [
    (Story) => (
      <TooltipProvider>
        <ChannelItemPreviewCardProvider>
          {/* The sidebar's own width, so the names truncate where they really do. */}
          <div className="w-[260px] p-2">
            {/* Every row is an Autocomplete option under the spaces layout, so it
                needs the same root the list gives it. */}
            <Autocomplete<string>
              inline
              open
              items={ROWS.map((row) => row.channel.id)}
              filter={null}
            >
              <AutocompleteList>
                <Story />
              </AutocompleteList>
            </Autocomplete>
          </div>
        </ChannelItemPreviewCardProvider>
      </TooltipProvider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ChannelSection>;

export const Rows: Story = {
  render: () => (
    <>
      {ROWS.map((row) => (
        <ChannelSection key={row.channel.id} {...row} />
      ))}
    </>
  ),
};
