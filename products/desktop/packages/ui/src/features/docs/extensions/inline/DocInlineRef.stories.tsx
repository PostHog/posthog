import { ChartLineIcon, FlagIcon } from "@phosphor-icons/react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { DocRefInline } from "./DocInlineRef";
import { DocRefDot } from "./DocRefDot";
import { DocRefIcon } from "./DocRefIcon";
import "@posthog/ui/features/docs/components/docs.css";

const meta: Meta<typeof DocRefInline> = {
  title: "Docs/Inline reference",
  component: DocRefInline,
  decorators: [
    (Story) => (
      <div className="doc-body" style={{ maxWidth: 620, padding: 24 }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof DocRefInline>;

function Line({ children }: { children: React.ReactNode }) {
  return <p style={{ marginBottom: 8 }}>{children}</p>;
}

/** Every kind and every status, in the prose they have to live in. */
export const InProse: Story = {
  render: () => (
    <>
      <Line>
        Signup volume dropped on Tuesday, so{" "}
        <DocRefInline
          state={{
            label: "Marcus",
            mark: <span className="doc-ref-avatar">M</span>,
            card: {
              title: "Marcus Chen",
              meta: <span>marcus@example.com</span>,
            },
          }}
        />{" "}
        opened{" "}
        <DocRefInline
          state={{
            label: "Signups fell after the new setup screen",
            mark: <DocRefDot tone="yellow" style="solid" pulse />,
            card: {
              title: "Signups fell after the new setup screen",
              meta: (
                <>
                  <DocRefDot tone="yellow" style="solid" pulse />
                  <span>Running</span>
                  <span>· posthog/posthog</span>
                  <span>· 2h ago</span>
                </>
              ),
            },
          }}
        />{" "}
        against{" "}
        <DocRefInline
          state={{
            label: "Weekly signups",
            mark: <DocRefIcon icon={ChartLineIcon} />,
            card: {
              title: "Weekly signups",
              meta: (
                <>
                  <span>Insight</span>
                  <span>· 4,182 last week</span>
                </>
              ),
              action: { label: "Open in PostHog", onSelect: () => undefined },
            },
            onOpen: () => undefined,
          }}
        />
        .
      </Line>
      <Line>
        The run stopped:{" "}
        <DocRefInline
          state={{
            label: "Roll back the setup screen",
            mark: <DocRefDot tone="red" style="solid" />,
          }}
        />
        , the follow-up is done:{" "}
        <DocRefInline
          state={{
            label: "Restore the old copy",
            mark: <DocRefDot tone="green" style="solid" />,
          }}
        />
        , and this one has not started:{" "}
        <DocRefInline
          state={{
            label: "Measure the second week",
            mark: <DocRefDot tone="gray" style="hollow" />,
          }}
        />
        .
      </Line>
      <Line>
        A reference the caret is on:{" "}
        <DocRefInline
          selected
          state={{
            label: "New setup screen",
            mark: <DocRefIcon icon={FlagIcon} />,
          }}
        />
        , and a phrase someone is discussing:{" "}
        <span className="doc-discussion-anchor">the second week of data</span>.
      </Line>
      <Line>
        A long title still breaks across the line:{" "}
        <DocRefInline
          state={{
            label:
              "Signups fell after the new setup screen shipped to everyone on Tuesday",
            mark: <DocRefDot tone="yellow" style="solid" pulse />,
          }}
        />
        .
      </Line>
    </>
  ),
};
