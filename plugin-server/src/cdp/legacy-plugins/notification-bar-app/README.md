# The Official PostHog Notification Bar App

## Installation

1. Make sure you have enabled `opt_in_site_apps: true` in your posthog-js config.
2. Install this app from PostHog's app repository.
3. Enable and configure the app for your site.

## Demo
![2022-10-14 13 28 39](https://user-images.githubusercontent.com/53387/195836509-a403817c-35f1-475c-a782-a6343511c361.gif)

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
