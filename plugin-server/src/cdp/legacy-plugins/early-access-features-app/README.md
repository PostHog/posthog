# Early Access Features App

Give your users the ability to opt-in to features

## Installation

1. Make sure you have enabled `opt_in_site_apps: true` in your posthog-js config init.
2. Install the app from the PostHog App Repository
3. Customise the text, and enable the plugin
4. Add a button with a corresponding data attribute e.g. `data-attr='posthog-beta-button'` which when clicked will open the beta widget


## Local development

For local development, clone the repo and run

```bash
npx @posthog/app-dev-server
```

or

```bash
pnpm install
pnpm start
```
