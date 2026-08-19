import { LinkIcon, StarIcon, TrashIcon } from "@phosphor-icons/react";
import { Card } from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ChannelActionItem } from "./channelActions";
import { SpacePreviewContent, type SpacePreviewPayload } from "./SpacePreview";

/**
 * The card as the sidebar shows it — the popup itself carries no styling of its
 * own, so the story supplies the same quill `Card` the shared preview card
 * renders it into.
 */
function CardFrame({
  people,
  total,
  ...payload
}: SpacePreviewPayload & { people: UserBasic[]; total: number | null }) {
  return (
    <div className="p-4">
      <Card
        size="sm"
        className="w-72 gap-0 border border-border py-0 shadow-md"
      >
        <SpacePreviewContent
          payload={payload}
          people={people}
          total={total}
          onAction={() => {}}
        />
      </Card>
    </div>
  );
}

function user(id: number, first: string, last: string): UserBasic {
  return {
    id,
    uuid: `user-${id}`,
    first_name: first,
    last_name: last,
    email: `${first.toLowerCase()}@example.com`,
  };
}

const actions: ChannelActionItem[] = [
  {
    key: "star",
    label: "Star space",
    icon: <StarIcon size={14} />,
    onSelect: () => {},
  },
  {
    key: "copy-link",
    label: "Copy link",
    icon: <LinkIcon size={14} />,
    onSelect: () => {},
  },
  {
    key: "delete",
    label: "Delete space…",
    icon: <TrashIcon size={14} />,
    variant: "destructive",
    onSelect: () => {},
  },
];

const meta = {
  title: "Canvas/SpacePreview",
  component: CardFrame,
  args: {
    channel: {
      id: "channel-1",
      name: "growth-engineering",
      channelType: "public" as const,
      starred: true,
      repositories: ["PostHog/posthog", "PostHog/posthog.com"],
      createdBy: user(1, "Ada", "Lovelace"),
    },
    unreadSessions: 0,
    blockedSessions: 0,
    actions,
    total: 14,
    people: [
      user(1, "Ada", "Lovelace"),
      user(2, "Grace", "Hopper"),
      user(3, "Alan", "Turing"),
      user(4, "Katherine", "Johnson"),
    ],
  },
} satisfies Meta<typeof CardFrame>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Nothing owed: the gutter stays empty and the card is who and what. */
export const Quiet: Story = {};

/** Both dots the row can show, spelled out. */
export const WantsYou: Story = {
  args: { unreadSessions: 3, blockedSessions: 2 },
};

/** More repos than the card names, and no creator on the record. */
export const ManyRepos: Story = {
  args: {
    people: [user(2, "Grace", "Hopper"), user(3, "Alan", "Turing")],
    channel: {
      id: "channel-2",
      name: "platform",
      channelType: "public",
      starred: false,
      repositories: [
        "PostHog/posthog",
        "PostHog/posthog.com",
        "PostHog/charts",
        "PostHog/vector",
      ],
      createdBy: null,
    },
  },
};
