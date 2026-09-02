import { describe, expect, it } from "vitest";
import { splitUserMessage, userMessageDisplayText } from "./userMessageDisplay";

const POSTHOG_CONTEXT =
  '<posthog_untrusted_context>\nThe user is currently looking at the resources below.\n- dashboard 42 ("Weekly active users")\n</posthog_untrusted_context>';
const CHANNEL_CONTEXT =
  '<channel_context channel="growth">\n- ship weekly\n</channel_context>';

describe("splitUserMessage", () => {
  it("peels every injected block off one message", () => {
    const parts = splitUserMessage(
      `${POSTHOG_CONTEXT}\n\nhow many monthly active users do we have\n\n${CHANNEL_CONTEXT}`,
    );
    expect(parts.displayContent).toBe(
      "how many monthly active users do we have",
    );
    expect(parts.posthogContext?.body).toBe(POSTHOG_CONTEXT);
    expect(parts.channelContext?.mention.name).toBe("growth");
  });

  it("gives the jump picker and minimap the question, not the context", () => {
    // Both label surfaces truncate hard, and the context blocks repeat across
    // messages — labelling raw content makes every row read the same.
    const label = userMessageDisplayText(
      `${POSTHOG_CONTEXT}\n\nwhy did signups drop`,
    );
    expect(label).toBe("why did signups drop");
  });
});
