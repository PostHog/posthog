import {
  AppWindow,
  FileText,
  type Icon,
  Robot,
  Scroll,
  SlackLogo,
  UserGear,
} from "@phosphor-icons/react";
import {
  channelDisplayLabel,
  channelDisplayReference,
} from "@posthog/core/canvas/channelName";
import type {
  InjectedBlock,
  InjectedBlockKind,
} from "@posthog/core/editor/injectedBlocks";

export interface InjectedBlockPresentation {
  icon: Icon;
  label: (block: InjectedBlock) => string;
  /** Hover text on the chip, for a block whose label needs explaining. */
  tooltip?: string;
  /**
   * Show a chip naming the block where the message renders. A block with no
   * chip is still stripped; it is background the reader did not ask about.
   */
  chip: boolean;
  /**
   * How the block renders when its chip opens it in a split tab. Absent, the
   * chip is inert. Opening is a project-bluebird feature, so a chip that would
   * open is hidden while the flag is off.
   */
  tab?: {
    intro: (block: InjectedBlock) => string;
    format: "markdown" | "raw";
  };
}

// Every kind the parser in @posthog/core knows needs an entry here; the type
// enforces it. This is the only place a block's label, icon and tab live, so
// the chat bubble, the activity timeline, the split tab and the tab strip all
// agree on what a block is called.
export const INJECTED_BLOCK_PRESENTATION: Record<
  InjectedBlockKind,
  InjectedBlockPresentation
> = {
  "channel-context": {
    icon: FileText,
    label: (block) =>
      `${block.attrs.channel ? `${channelDisplayLabel(block.attrs.channel)} ` : ""}CONTEXT.md`,
    chip: true,
    tab: {
      intro: (block) =>
        `Sent with this task's prompt as background context${
          block.attrs.channel
            ? ` from ${channelDisplayReference(block.attrs.channel)}`
            : ""
        }.`,
      format: "markdown",
    },
  },
  "canvas-instructions": {
    icon: Scroll,
    label: () => "Canvas instructions",
    chip: true,
    tab: {
      intro: () =>
        "Sent with this task's prompt: the canvas authoring contract the agent followed.",
      format: "markdown",
    },
  },
  "posthog-context": {
    icon: AppWindow,
    label: () => "PostHog context",
    chip: true,
    tab: {
      intro: () =>
        "Sent with this message from PostHog, exactly as the agent received it.",
      format: "raw",
    },
  },
  "custom-instructions": {
    icon: UserGear,
    label: () => "Personalization",
    chip: false,
  },
  "onboarding-brief": {
    icon: Robot,
    label: () => "Getting started with PostHog Desktop",
    tooltip:
      "The agent is looking over your project to help set up the PostHog Desktop experience.",
    chip: true,
  },
  "slack-thread": {
    icon: SlackLogo,
    label: () => "Slack thread",
    chip: false,
  },
};

/** The blocks a message surface shows chips for, given whether tabs can open. */
export function visibleInjectedBlocks(
  blocks: InjectedBlock[],
  canOpenTabs: boolean,
): InjectedBlock[] {
  return blocks.filter((block) => {
    const { chip, tab } = INJECTED_BLOCK_PRESENTATION[block.kind];
    return chip && (canOpenTabs || !tab);
  });
}
