import {
  POSTHOG_PRODUCTS,
  type PostHogProductId,
} from "@posthog/agent/posthog-products";
import type { AcpMessage } from "@posthog/shared";
import { SessionResourcesBar } from "@posthog/ui/features/sessions/components/SessionResourcesBar";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof SessionResourcesBar> = {
  title: "Sessions/SessionResourcesBar",
  component: SessionResourcesBar,
  parameters: {
    layout: "fullscreen",
  },
};

export default meta;
type Story = StoryObj<typeof SessionResourcesBar>;

/**
 * Build the `_posthog/resources_used` notification the bar accumulates from,
 * one product per event — mirroring how the agent reports usage turn by turn.
 */
const resourcesUsedEvents = (ids: PostHogProductId[]): AcpMessage[] =>
  ids.map((id, index) => ({
    type: "acp_message" as const,
    ts: index + 1,
    message: {
      jsonrpc: "2.0" as const,
      method: "_posthog/resources_used",
      params: {
        sessionId: "session-1",
        products: [{ id, label: POSTHOG_PRODUCTS[id] }],
      },
    },
  }));

const ALL_PRODUCT_IDS = Object.keys(POSTHOG_PRODUCTS) as PostHogProductId[];

export const FewResources: Story = {
  args: {
    events: resourcesUsedEvents([
      "feature_flags",
      "experiments",
      "product_analytics",
    ]),
  },
  parameters: {
    docs: {
      description: {
        story:
          "The common case: a handful of compact chips on a single row, each linking to the product's docs.",
      },
    },
  },
};

export const AtChipLimit: Story = {
  args: {
    events: resourcesUsedEvents([
      "product_analytics",
      "web_analytics",
      "feature_flags",
      "experiments",
      "error_tracking",
      "session_replay",
    ]),
  },
  parameters: {
    docs: {
      description: {
        story:
          "Exactly six products — the maximum shown before collapsing — so no overflow badge appears.",
      },
    },
  },
};

export const OverflowCollapsed: Story = {
  args: {
    events: resourcesUsedEvents(ALL_PRODUCT_IDS),
  },
  parameters: {
    docs: {
      description: {
        story:
          "Every product used: only the first six chips render, with the rest collapsed behind a clickable “+N more” badge that toggles to “Show less”.",
      },
    },
  },
};

export const WithNonClickableChip: Story = {
  args: {
    events: resourcesUsedEvents(["llm_analytics", "apm", "logs"]),
  },
  parameters: {
    docs: {
      description: {
        story:
          "APM has no dedicated docs page, so its chip renders without a pointer cursor, hover state, or link.",
      },
    },
  },
};

export const NarrowContainer: Story = {
  args: {
    events: resourcesUsedEvents([
      "product_analytics",
      "data_warehouse",
      "error_tracking",
    ]),
  },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 130 }}>
        <Story />
      </div>
    ),
  ],
  parameters: {
    docs: {
      description: {
        story:
          "In a narrow container, chips wrap and a label wider than the row truncates with an ellipsis instead of overflowing.",
      },
    },
  },
};

export const NoResources: Story = {
  args: {
    events: [],
  },
  parameters: {
    docs: {
      description: {
        story: "When no products have been used yet, the bar is hidden.",
      },
    },
  },
};
