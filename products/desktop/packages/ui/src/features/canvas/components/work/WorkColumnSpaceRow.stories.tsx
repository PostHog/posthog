import type { ChannelPresence } from "@posthog/core/canvas/presence";
import { Autocomplete, AutocompleteList, MenuLabel } from "@posthog/quill";
import type { Task, UserBasic } from "@posthog/shared/domain-types";
import { ChannelItemPreviewCardProvider } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { SpaceRow } from "./WorkColumn";

function user(id: number, first: string, last: string): UserBasic {
  return {
    id,
    uuid: `user-${id}`,
    first_name: first,
    last_name: last,
    email: `${first.toLowerCase()}@example.com`,
  };
}

const ada = user(1, "Ada", "Lovelace");
const grace = user(2, "Grace", "Hopper");
const alan = user(3, "Alan", "Turing");
const katherine = user(4, "Katherine", "Johnson");

const MINUTE = 60_000;

interface SpaceFixture {
  channel: Channel;
  faces?: { people: UserBasic[]; live?: UserBasic[] };
  unreadSessions?: number;
  blockedSessions?: number;
  sessions: { by: UserBasic; minutesAgo: number }[];
}

function channel(name: string, overrides: Partial<Channel> = {}): Channel {
  return {
    id: `space-${name}`,
    name,
    channelType: "public",
    starred: true,
    repositories: [],
    createdBy: ada,
    ...overrides,
  };
}

const SPACES: SpaceFixture[] = [
  {
    channel: channel("personal", {
      channelType: "personal",
      systemRole: "personal",
    }),
    sessions: [{ by: ada, minutesAgo: 30 }],
  },
  {
    channel: channel("design-system", {
      repositories: ["example-org/webapp"],
    }),
    sessions: [
      { by: grace, minutesAgo: 60 * 26 },
      { by: ada, minutesAgo: 60 * 50 },
    ],
  },
  {
    channel: channel("billing", { repositories: ["example-org/billing"] }),
    faces: { people: [grace], live: [grace] },
    sessions: [
      { by: grace, minutesAgo: 1 },
      { by: alan, minutesAgo: 90 },
    ],
  },
  {
    channel: channel("growth-engineering", {
      createdBy: alan,
      repositories: ["example-org/webapp", "example-org/website"],
    }),
    faces: { people: [alan, katherine] },
    unreadSessions: 3,
    blockedSessions: 1,
    sessions: [
      { by: katherine, minutesAgo: 12 },
      { by: alan, minutesAgo: 40 },
      { by: grace, minutesAgo: 60 * 5 },
    ],
  },
  {
    channel: channel("onboarding", { createdBy: katherine }),
    unreadSessions: 1,
    sessions: [{ by: katherine, minutesAgo: 60 * 3 }],
  },
  {
    channel: channel("web-analytics", { repositories: ["example-org/webapp"] }),
    faces: { people: [katherine], live: [katherine] },
    sessions: [{ by: katherine, minutesAgo: 2 }],
  },
  {
    channel: channel("release-notes", {
      repositories: ["example-org/website"],
    }),
    sessions: [{ by: ada, minutesAgo: 60 * 24 * 3 }],
  },
  {
    channel: channel("launch-planning", { channelType: "private" }),
    sessions: [
      { by: ada, minutesAgo: 60 * 8 },
      { by: grace, minutesAgo: 60 * 9 },
    ],
  },
];

function presenceOf(space: SpaceFixture): ChannelPresence | undefined {
  if (!space.faces) return undefined;
  return {
    people: space.faces.people,
    liveUuids: new Set((space.faces.live ?? []).map((person) => person.uuid)),
  };
}

function SeededSpaces({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  useState(() => {
    const now = Date.now();
    for (const space of SPACES) {
      const tasks = space.sessions.map(
        ({ by, minutesAgo }, index) =>
          ({
            id: `${space.channel.id}-task-${index}`,
            created_by: by,
            last_activity_at: new Date(now - minutesAgo * MINUTE).toISOString(),
          }) as Task,
      );
      queryClient.setQueryData(["space-tree-tasks", space.channel.id], {
        tasks,
        count: tasks.length,
      });
    }
    return null;
  });
  return <>{children}</>;
}

function SpaceRows() {
  return (
    <>
      {SPACES.map((space) => (
        <SpaceRow
          key={space.channel.id}
          channel={space.channel}
          isActive={false}
          unread={
            (space.unreadSessions ?? 0) + (space.blockedSessions ?? 0) > 0
          }
          unreadSessions={space.unreadSessions ?? 0}
          blockedSessions={space.blockedSessions ?? 0}
          presence={presenceOf(space)}
        />
      ))}
    </>
  );
}

const meta: Meta<typeof SpaceRows> = {
  title: "Spaces/WorkColumnSpaceRow",
  component: SpaceRows,
  decorators: [
    (Story) => (
      <SeededSpaces>
        <ChannelItemPreviewCardProvider>
          <div className="w-[300px] bg-chrome p-2">
            <MenuLabel className="py-1 font-semibold text-foreground/70">
              Spaces
            </MenuLabel>
            <Autocomplete<string>
              inline
              open
              items={SPACES.map((space) => space.channel.id)}
              filter={null}
            >
              <AutocompleteList className="flex flex-col gap-px">
                <Story />
              </AutocompleteList>
            </Autocomplete>
          </div>
        </ChannelItemPreviewCardProvider>
      </SeededSpaces>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof SpaceRows>;

export const Rows: Story = {};
