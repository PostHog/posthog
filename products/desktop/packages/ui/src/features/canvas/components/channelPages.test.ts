import { CHANNEL_SECTIONS } from "@posthog/ui/features/canvas/channelSections";
import {
  CHANNEL_PAGES,
  type ChannelPageKey,
} from "@posthog/ui/features/canvas/components/channelPages";
import { describe, expect, it } from "vitest";

describe("CHANNEL_PAGES", () => {
  // The two tables are keyed the same on purpose: channelSections carries the
  // route segment (plain data, read by non-UI code), CHANNEL_PAGES carries the
  // label and icon. A section with no page entry would render an unlabelled,
  // icon-less breadcrumb leaf, so fail here instead.
  it("has an entry for every routable channel section", () => {
    for (const section of CHANNEL_SECTIONS) {
      expect(CHANNEL_PAGES[section.key as ChannelPageKey]).toBeDefined();
    }
  });

  it("gives every page a label", () => {
    for (const page of Object.values(CHANNEL_PAGES)) {
      expect(page.label.trim()).not.toBe("");
    }
  });
});
