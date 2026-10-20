# Slack domain helpers

Code about Slack that more than one product needs, and that is neither transport nor an outbound call.
Inbound transport is `posthog/ingress/slack/`.
Outbound calls go through `posthog/egress/slack/`.
Neither of those imports the other, and both may import this package.

## What belongs here

Knowledge about Slack itself, which changes when Slack changes.
Examples are how to escape `mrkdwn`, the limits Slack puts on a message, the format of a stored channel picker value, how to find a channel by name, and how to resolve a Slack user to a PostHog user.

## What stays with the product

Some code looks the same in two products but changes for product reasons.
That code stays in each product:

- Where a message goes: destination storage and routing.
- What a message says.
- What a failed post does: which Slack error codes a product treats as permanent, as retryable, or as a reason to disable a destination.
- Thread state: where a product stores the root message of a thread, and when it posts a reply instead of a new message.

Two copies of this kind of code are not duplication to remove.
Move code here only when every caller changes it for the same Slack reason.
