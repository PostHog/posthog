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
  tooltip?: string;
  chip: boolean;
  tab?: {
    intro: (block: InjectedBlock) => string;
    format: "markdown" | "raw";
  };
}

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

export function visibleInjectedBlocks(
  blocks: InjectedBlock[],
  canOpenTabs: boolean,
): InjectedBlock[] {
  return blocks.filter((block) => {
    const { chip, tab } = INJECTED_BLOCK_PRESENTATION[block.kind];
    return chip && (canOpenTabs || !tab);
  });
}
