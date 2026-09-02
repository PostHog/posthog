import {
  type Announcement,
  announcementSchema,
} from "@posthog/shared/announcements";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { AnnouncementModal } from "./AnnouncementModal";

type ModalAnnouncement = Extract<Announcement, { kind: "announcement" }>;

const MARKDOWN_BODY = [
  "PostHog Desktop now runs **recurring agent jobs** straight from your project.",
  "",
  "- Schedule a prompt on any cadence",
  "- Route the results to Self-driving or a channel",
  "- Pause or rewire a loop without a release",
  "",
  "Read the [docs](https://posthog.com/docs) for the full tour.",
].join("\n");

/** Parse through the real schema so fixtures stay valid payload examples. */
function modalAnnouncement(
  overrides: Record<string, unknown> = {},
): ModalAnnouncement {
  const parsed = announcementSchema.parse({
    kind: "announcement",
    id: "storybook-announcement",
    title: "Loops are here",
    body: MARKDOWN_BODY,
    style: "modal",
    cta: { label: "Try loops", url: "posthog-code://loop/storybook" },
    ...overrides,
  });
  if (parsed.kind !== "announcement") {
    throw new Error("fixture must be an announcement");
  }
  return parsed;
}

const meta: Meta<typeof AnnouncementModal> = {
  title: "Announcements/AnnouncementModal",
  component: AnnouncementModal,
  args: { needsUpdate: false },
};

export default meta;
type Story = StoryObj<typeof AnnouncementModal>;

/** The default look: hero band with the default hedgehog, markdown body, CTA. */
export const Default: Story = {
  args: { announcement: modalAnnouncement() },
};

/** Payload-driven hero: custom band color and a hoggie from the brand catalog (CDN-loaded). */
export const CatalogHeroHoggie: Story = {
  args: {
    announcement: modalAnnouncement({
      hero: { hedgehog: "dr-manhattan", color: "#1d4aff" },
    }),
  },
};

/** `hero: { none: true }` drops the band for a plain modal. */
export const NoHero: Story = {
  args: { announcement: modalAnnouncement({ hero: { none: true } }) },
};

/** `requiresAck` blocks: no close button, no Esc, no dismiss — only the ack button. */
export const BlockingAck: Story = {
  args: {
    announcement: modalAnnouncement({
      requiresAck: true,
      ackLabel: "I understand",
      title: "Billing has changed",
      body: "Usage-based billing replaces seat-based plans. You only pay for what you use.",
    }),
  },
};

/**
 * Below `minVersion` the CTA swaps for the update action. Storybook has no
 * updater, so the action degrades to the manual-download link.
 */
export const NeedsUpdate: Story = {
  args: {
    announcement: modalAnnouncement({ minVersion: "9.9.9" }),
    needsUpdate: true,
  },
};

/** A remote-length body scrolls inside the dialog body; the footer stays reachable. */
export const LongBody: Story = {
  args: {
    announcement: modalAnnouncement({
      body: Array.from({ length: 12 }, () => MARKDOWN_BODY).join("\n\n"),
    }),
  },
};
