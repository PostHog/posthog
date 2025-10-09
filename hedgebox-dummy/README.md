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

The app automatically fetches the PostHog API key from your local database at build/dev time. You can configure the database connection and team ID using these environment variables:

```env
NEXT_PUBLIC_POSTHOG_HOST # PostHog host (default: http://localhost:8010)
NEXT_PUBLIC_POSTHOG_KEY  # PostHog API key, fetched automatically on `npm run dev`
DEMO_TEAM_ID             # Team ID to fetch token from (default: latest team)
```

**Note:** The API key is automatically fetched and written to `.env.local` when you run `npm run dev` or `npm run build`. The script will skip fetching if `.env.local` already exists (to avoid unnecessary database queries on every run).

To manually fetch the key or force a re-fetch, run:

```bash
# Fetch if .env.local doesn't exist or doesn't have key NEXT_PUBLIC_POSTHOG_KEY
npm run fetch-posthog-key
# Force re-fetch even if NEXT_PUBLIC_POSTHOG_KEY set in .env.local
FORCE_FETCH_KEY=1 npm run fetch-posthog-key
```

Alternatively, you can manually create a `.env.local` file with the `NEXT_*` vars above.

3. Run the development server:

```bash
npm run dev
```

The app will be available at [http://localhost:3000](http://localhost:3000).

## Generating session recordings

The app is instrumented as long as `npm run dev` has `NEXT_PUBLIC_POSTHOG_KEY` set. Just interact normally and recordings will be captured in your PostHog instance.
