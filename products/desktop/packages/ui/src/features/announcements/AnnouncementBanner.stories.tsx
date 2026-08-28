import {
  type Announcement,
  announcementSchema,
} from "@posthog/shared/announcements";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { BannerRow } from "./AnnouncementBanner";

type BannerAnnouncement = Extract<Announcement, { kind: "announcement" }>;

/** Parse through the real schema so fixtures stay valid payload examples. */
function bannerAnnouncement(
  overrides: Record<string, unknown> = {},
): BannerAnnouncement {
  const parsed = announcementSchema.parse({
    kind: "announcement",
    id: "storybook-banner",
    title: "Loops are here",
    body: "Schedule **recurring agent jobs** and route results to [Self-driving](posthog-code://inbox/demo).\nBanners render only this first line.",
    cta: { label: "Try loops", url: "posthog-code://loop/storybook" },
    ...overrides,
  });
  if (parsed.kind !== "announcement") {
    throw new Error("fixture must be an announcement");
  }
  return parsed;
}

const meta: Meta<typeof BannerRow> = {
  title: "Announcements/AnnouncementBanner",
  component: BannerRow,
  args: { needsUpdate: false },
  // The banner spans the top of the app shell; give it a realistic width.
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 960, margin: "1rem auto" }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof BannerRow>;

/** Title, the body's first line, a CTA, and the dismiss button. */
export const Default: Story = {
  args: { announcement: bannerAnnouncement() },
};

/** No CTA: just the message and dismiss. */
export const NoCta: Story = {
  args: { announcement: bannerAnnouncement({ cta: undefined }) },
};

/**
 * Below `minVersion` the CTA swaps for the update action. Storybook has no
 * updater, so the action degrades to the manual-download link.
 */
export const NeedsUpdate: Story = {
  args: {
    announcement: bannerAnnouncement({ minVersion: "9.9.9" }),
    needsUpdate: true,
  },
};

/** Long copy truncates rather than growing the banner. */
export const LongCopy: Story = {
  args: {
    announcement: bannerAnnouncement({
      title:
        "A very long announcement title that should still keep the banner to a single compact row",
      body: "An even longer first body line that is truncated with an ellipsis instead of wrapping onto multiple lines and pushing the actions around.",
    }),
  },
};
