# Hedgebox dummy app

This app represents our Hedgebox product simulation for demo data purposes.

## Background

We've had a [demo data generator](../posthog/demo/products/hedgebox/) simulating a product called Hedgebox (like Dropbox for hedgehogs) for a while now. It creates realistic event data with user profiles, behaviors, timezones, even includes features like a Marius Tech Tips sponsorship landing page and an A/B test on the signup flow.

However, the generator hasn't been able to create session recording data, as that's a hard nut to ~~crack~~ store. Session recordings need an actual app with actual user interactions to capture. Hedgebox never had one - until now.

This dummy app brings Hedgebox to life as a working Next.js app that can be used to generate real session recordings for demos and testing.

## What's Inside

A fully functional (fake) demo app with:

- Login/signup flows
- File management interface
- Pricing page
- Marius Tech Tips landing page
- PostHog integration for tracking and session recording

## Setup

1. Install dependencies:

```bash
npm install
```

2. Set up PostHog environment variables:

Create a `.env.local` file in this directory with:

```env
NEXT_PUBLIC_POSTHOG_KEY=your_posthog_project_api_key
NEXT_PUBLIC_POSTHOG_HOST=http://localhost:8010
```

- `NEXT_PUBLIC_POSTHOG_KEY` - Your PostHog project API key (if not set, posthog-js will be disabled)
- `NEXT_PUBLIC_POSTHOG_HOST` - Your PostHog instance URL (if not set, defaults to `http://localhost:8010`)

3. Run the development server:

```bash
npm run dev
```

The app will be available at [http://localhost:3000](http://localhost:3000).

## Generating session recordings

The app is instrumented as long as `npm run dev` has `NEXT_PUBLIC_POSTHOG_KEY` set. Just interact normally and recordings will be captured in your PostHog instance.
