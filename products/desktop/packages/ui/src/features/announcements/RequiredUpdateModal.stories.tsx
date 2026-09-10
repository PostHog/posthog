import {
  type Announcement,
  announcementSchema,
} from "@posthog/shared/announcements";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { RequiredUpdateModal } from "./RequiredUpdateModal";

type RequiredUpdate = Extract<Announcement, { kind: "required-update" }>;

/** Parse through the real schema so fixtures stay valid payload examples. */
function requiredUpdate(
  overrides: Record<string, unknown> = {},
): RequiredUpdate {
  const parsed = announcementSchema.parse({
    kind: "required-update",
    id: "storybook-required-update",
    title: "Update required",
    body: "This version can no longer talk to the PostHog backend. Update to keep your tasks and loops running.",
    minVersion: "9.9.9",
    ...overrides,
  });
  if (parsed.kind !== "required-update") {
    throw new Error("fixture must be a required update");
  }
  return parsed;
}

const meta: Meta<typeof RequiredUpdateModal> = {
  title: "Announcements/RequiredUpdateModal",
  component: RequiredUpdateModal,
};

export default meta;
type Story = StoryObj<typeof RequiredUpdateModal>;

/**
 * Fully blocking: no close button, Esc and outside clicks do nothing — the
 * update action is the only way forward. Storybook has no updater, so the
 * action degrades to the manual-download link.
 */
export const Default: Story = {
  args: { announcement: requiredUpdate() },
};

/** The hero band follows the payload here too. */
export const CustomHero: Story = {
  args: {
    announcement: requiredUpdate({
      hero: { hedgehog: "explorer", color: "#111827" },
    }),
  },
};
