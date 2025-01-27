![Avo logo](logo.png)

# Avo Inspector Plugin

Send events to the [Avo Inspector](https://www.avo.app/docs/workspace/inspector#Overview) to detect inconsistencies.

## About Avo Inspector

_Excerpt from the [Avo docs](https://www.avo.app/docs/workspace/inspector#Overview)._

> The first step to better analytics governance is knowing what's wrong with your data today.
>
> We built the Inspector to help you understand how your current tracking is performing. The Inspector both identifies common issues in your existing tracking, such as inconsistent properties and types, and provides implementation status in the Avo Tracking Plan, so you always know the state of your tracking implementation in your app.

## Questions?

### [Join the PostHog community.](https://posthog.com/questions)

## Debugging tips

1. use `dev` env when testing as prod could show up hours later
2. `messageId` needs to unique based on testing to send curls (potentially used for deduping within Avo)
3. There's user and pass for an account in 1Password
4. Within the Avo click on Events under Inspector [link](https://www.avo.app/schemas/QtBfxYTrDv36SU3dsre0/inspector/events?order=Ascending&orderBy=EventName&shareId=tVkfNWEt5e)
