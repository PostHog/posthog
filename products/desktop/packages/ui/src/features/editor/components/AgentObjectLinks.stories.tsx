import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { useEffect } from "react";

const PROJECT = "https://us.posthog.com/project/2";
const sql = (query: string) =>
  `${PROJECT}/sql?open_query=${encodeURIComponent(query)}`;

const signedIn: Decorator = (Story) => {
  useEffect(() => {
    const previous = useAuthStore.getState().authState;
    useAuthStore.setState({
      authState: {
        ...ANONYMOUS_AUTH_STATE,
        cloudRegion: "us",
        currentProjectId: 2,
      },
    });
    return () => useAuthStore.setState({ authState: previous });
  }, []);
  return (
    <div className="max-w-xl">
      <Story />
    </div>
  );
};

const meta: Meta<typeof MarkdownRenderer> = {
  title: "Features/Editor/Agent object links",
  component: MarkdownRenderer,
  decorators: [signedIn],
  parameters: { layout: "padded" },
};

export default meta;
type Story = StoryObj<typeof MarkdownRenderer>;

export const AgentReply: Story = {
  args: {
    renderObjectTags: true,
    content: [
      `The [coupon to purchase conversion](${PROJECT}/insights/9pQx3) dropped from 41% to 28% on Jan 3. [A TypeError in CouponValidator](${PROJECT}/error_tracking/018f44aa-0000-7000-8000-000000000001) first appeared the same day, behind [new-checkout-flow](${PROJECT}/feature_flags/42). [1,247 sessions](${sql("SELECT count(DISTINCT $session_id) FROM events WHERE event = '$exception'")}) hit the error this week.`,
      "",
      `[Daily active users, last 7 days](${sql("SELECT toDate(timestamp) AS day, count(DISTINCT person_id) AS dau FROM events WHERE timestamp >= now() - INTERVAL 7 DAY GROUP BY day ORDER BY day")} "The drop on Aug 14 lines up with the checkout deploy.")`,
      "",
      "The saved funnel shows the same drop:",
      "",
      `[Coupon funnel, last 30 days](${PROJECT}/insights/9pQx3)`,
      "",
      "One user retried the coupon field four times before they left:",
      "",
      `[The failed checkout](${PROJECT}/replay/0190f8a1-sess?t=42)`,
    ].join("\n"),
  },
};

export const LinksThatStayPlain: Story = {
  args: {
    renderObjectTags: true,
    content: [
      `- An insight in [another project](https://us.posthog.com/project/3/insights/9pQx3) or [another region](https://eu.posthog.com/project/2/insights/9pQx3) stays a plain link.`,
      `- A page that is not an object, like [project settings](${PROJECT}/settings/project), stays a plain link.`,
      `- A flag cited by key, like [new-checkout-flow](${PROJECT}/feature_flags/new-checkout-flow), has no page, so it stays a plain link.`,
      `- A chart link inside a list, like [DAU](${sql("SELECT 1")}), stays an inline chip.`,
      `- Code stays code: \`[DAU](${PROJECT}/insights/9pQx3)\``,
      "- The docs stay a normal link: [PostHog docs](https://posthog.com/docs).",
    ].join("\n"),
  },
};

export const TagsAndLinksRenderTheSame: Story = {
  render: () => (
    <div className="flex flex-col gap-4">
      <MarkdownRenderer
        renderObjectTags
        content={`Old tags: the <insight id="9pQx3">checkout funnel</insight> dropped after <flag id="42">new-checkout-flow</flag> rolled out, see <hogql label="errors today">SELECT count() FROM events WHERE event = '$exception'</hogql>.`}
      />
      <MarkdownRenderer
        renderObjectTags
        content={`New links: the [checkout funnel](${PROJECT}/insights/9pQx3) dropped after [new-checkout-flow](${PROJECT}/feature_flags/42) rolled out, see [errors today](${sql("SELECT count() FROM events WHERE event = '$exception'")}).`}
      />
    </div>
  ),
};

export const UntrustedContent: Story = {
  args: {
    content: `A user pasted [this chart](${sql("SELECT 1")}) and [this insight](${PROJECT}/insights/9pQx3). User content never runs queries, so both stay plain links.`,
  },
};
