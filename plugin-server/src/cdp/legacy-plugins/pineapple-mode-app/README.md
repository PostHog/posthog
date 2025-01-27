This is a sample [PostHog Site App](https://github.com/PostHog/meta/issues/63).

# 🍍🍍🍍 Pineapple Mode 🍍🍍🍍

Because everything's better with falling pineapples.

![2022-10-13 16 38 04](https://user-images.githubusercontent.com/53387/195627275-5dce555c-93f0-4011-a349-069e9fe22aab.gif)
![2022-10-13 16 36 01](https://user-images.githubusercontent.com/53387/195626733-928d5965-df71-4477-9e23-dcfbd342d08a.gif)

## Installation

1. Make sure you have enabled `opt_in_site_apps: true` in your posthog-js config.
2. Install this app from PostHog's app repository.
3. Enable and configure the app for your site.

## Template for your project

To use this project as a local template, run:

```bash
npx degit posthog/pineapple-mode-app my-new-app
cd my-new-app
pnpm install
pnpm start
```

## Local development

If you wish to make this a juicier example app, then clone the repo and run the following:

```bash
npx @posthog/app-dev-server
```

or

```bash
pnpm install
pnpm start
```

Then browse to [http://localhost:3040/](http://localhost:3040/), open `site.ts` in an editor, and hack away. 
