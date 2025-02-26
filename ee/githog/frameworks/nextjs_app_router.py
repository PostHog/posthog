import fnmatch
from typing import List

from .config import GitHogFrameworkConfig, GitHogFrameworkName


def detect_nextjs_app_router(all_files: List[str]) -> bool:

    has_app_layout = any(fnmatch.fnmatch(file, "app/layout.*") for file in all_files)
    
    has_pages_app = any(fnmatch.fnmatch(file, "pages/_app.*") for file in all_files)
    
    if has_app_layout and not (has_pages_app):
        return True
    return False

NEXTJS_APP_ROUTER_CONFIG = GitHogFrameworkConfig(
    name=GitHogFrameworkName.NEXTJS_APP_ROUTER,
    detect=detect_nextjs_app_router,
    filter_patterns=['*.js', '*.jsx', '*.ts', '*.tsx'],
    include_patterns=["package.json"],
    ignore_patterns=["node_modules/*", "dist/*", ".git/*", ".github/*", "*.md", "LICENSE"],
    create_patterns=['.env.example'],
    pr_instructions="""
1. To finish integrating PostHog into your Next.js app, you need to run `npm / yarn / pnpm install` to update your lockfile.
2. Add  NEXT_PUBLIC_POSTHOG_KEY=your-posthog-api-key to your environment variables - you can find this in your PostHog project settings.
""",
    installation_instructions="""
PostHog makes it easy to get data about traffic and usage of your Next.js app. Integrating PostHog into your site enables analytics about user behavior, custom events capture, session recordings, feature flags, and more.

This guide walks you through integrating PostHog into your Next.js app using the React and the Node.js SDKs.

You can see a working example of this integration in our Next.js demo app.

Next.js has both client and server-side rendering, as well as pages and app routers. We'll cover all of these options in this guide.


Prerequisites
To follow this guide along, you need:

A PostHog instance (either Cloud or self-hosted)
A Next.js application

Client-side setup
Install posthog-js using your package manager:

Terminal

yarn add posthog-js
# or
npm install --save posthog-js
# or
pnpm add posthog-js
Add your environment variables to your .env.local file and to your hosting provider (e.g. Vercel, Netlify, AWS). You can find your project API key in your project settings.

.env.local

NEXT_PUBLIC_POSTHOG_KEY=your-posthog-api-key
NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
These values need to start with NEXT_PUBLIC_ to be accessible on the client-side.


Router-specific instructions
App router
Pages router
If your Next.js app to uses the app router, you can integrate PostHog by creating a providers file in your app folder. This is because the posthog-js library needs to be initialized on the client-side using the Next.js 'use client' directive.

JSX
TSX

// app/providers.jsx
'use client'

import posthog from 'posthog-js'
import { PostHogProvider as PHProvider } from 'posthog-js/react'
import { useEffect } from 'react'

export function PostHogProvider({ children }) {
  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
      capture_pageview: false // Disable automatic pageview capture, as we capture manually
    })
  }, [])

  return (
    <PHProvider client={posthog}>
      {children}
    </PHProvider>
  )
}
Then, import the PostHogProvider component into your app/layout file and wrap your app with it.

JSX
TSX

// app/layout.jsx

import './globals.css'
import { PostHogProvider } from './providers'

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <PostHogProvider>
          {children}
        </PostHogProvider>
      </body>
    </html>
  )
}
PostHog is now set up and ready to go. Files and components accessing PostHog on the client-side need the 'use client' directive.


Capturing pageviews
PostHog's $pageview autocapture relies on page load events. Since Next.js acts as a single-page app, this event doesn't trigger on navigation and we need to capture $pageview events manually.

To do this, we set up a PostHogPageView component to listen to URL path changes:

JSX
TSX

// app/PostHogPageView.jsx
'use client'

import { usePathname, useSearchParams } from "next/navigation"
import { useEffect, Suspense } from "react"
import { usePostHog } from 'posthog-js/react'

function PostHogPageView() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const posthog = usePostHog()

  // Track pageviews
  useEffect(() => {
    if (pathname && posthog) {
      let url = window.origin + pathname
      if (searchParams.toString()) {
        url = url + `?${searchParams.toString()}`
      }

      posthog.capture('$pageview', { '$current_url': url })
    }
  }, [pathname, searchParams, posthog])
  
  return null
}

// Wrap this in Suspense to avoid the `useSearchParams` usage above
// from de-opting the whole app into client-side rendering
// See: https://nextjs.org/docs/messages/deopted-into-client-rendering
export default function SuspendedPostHogPageView() {
  return <Suspense fallback={null}>
    <PostHogPageView />
  </Suspense>
}
We can then update our PostHogProvider to include this component in all of our pages.

diff

// app/providers.js
  'use client'
  import posthog from 'posthog-js'
  import { PostHogProvider as PHProvider } from 'posthog-js/react'
  import { useEffect } from 'react'
+ import PostHogPageView from "./PostHogPageView"

  export function PostHogProvider({ children }) {
    useEffect(() => {
      posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
        api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
        capture_pageview: false // Disable automatic pageview capture, as we capture manually
      })
    }, [])
  
    return (
      <PHProvider client={posthog}>
+       <PostHogPageView />
        {children}
      </PHProvider>
    )
  }
Note: Make sure you list <PostHogPageView /> above {children} or else you might find your application is not keeping track of the initial $pageview event

Note: For older versions of Next.js (< 15), you might need to dynamically import PostHogPageView instead of using a <Suspense>. This is because of a known issue where server rendering a <Suspense> throws an error.

JavaScript

import dynamic from 'next/dynamic'

const PostHogPageView = dynamic(() => import('./PostHogPageView'), {
  ssr: false,
})

Capturing pageleave events (optional)
To capture pageleave events, we need to set capture_pageleave: true in the initialization because setting capture_pageview: false disables it.

diff

// app/providers.js
  'use client'
  import posthog from 'posthog-js'
  import { PostHogProvider as PHProvider } from 'posthog-js/react'
  import { useEffect } from 'react'
  export function PostHogProvider({ children }) {
    useEffect(() => {
      posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
        api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
        capture_pageview: false,
+       capture_pageleave: true, // Enable pageleave capture
      })
    }, [])
    return <PHProvider client={posthog}>{children}</PHProvider>
  }

Accessing PostHog using the provider
PostHog can then be accessed throughout your Next.js app by using the usePostHog hook. See the React SDK docs for examples of how to use:

posthog-js functions like custom event capture, user identification, and more.
Feature flags including variants and payloads.
You can also read the full posthog-js documentation for all the usable functions.


Server-side analytics
Server-side rendering enables you to render pages on the server instead of the client. This can be useful for SEO, performance, and user experience.

To integrate PostHog into your Next.js app on the server-side, you can use the Node SDK.

First, install the posthog-node library:

Terminal

yarn add posthog-node
# or
npm install --save posthog-node

Router-specific instructions
App router
Pages router
For the app router, we can initialize the posthog-node SDK once with a PostHogClient function, and import it into files.

This enables us to send events and fetch data from PostHog on the server – without making client-side requests.

JavaScript

// app/posthog.js
import { PostHog } from 'posthog-node'

export default function PostHogClient() {
  const posthogClient = new PostHog(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
    host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
    flushAt: 1,
    flushInterval: 0
  })
  return posthogClient
}
Note: Because server-side functions in Next.js can be short-lived, we set flushAt to 1 and flushInterval to 0.

flushAt sets how many capture calls we should flush the queue (in one batch).
flushInterval sets how many milliseconds we should wait before flushing the queue. Setting them to the lowest number ensures events are sent immediately and not batched. We also need to call await posthog.shutdown() once done.
To use this client, we import it into our pages and call it with the PostHogClient function:

JavaScript

import Link from 'next/link'
import PostHogClient from '../posthog'

export default async function About() {

  const posthog = PostHogClient()
  const flags = await posthog.getAllFlags(
    'user_distinct_id' // replace with a user's distinct ID
  );
  await posthog.shutdown()

  return (
    <main>
      <h1>About</h1>
      <Link href="/">Go home</Link>
      { flags['main-cta'] &&
        <Link href="http://posthog.com/">Go to PostHog</Link>
      }
    </main>
  )
}

Server-side Configuration
NextJS overrides the default fetch behaviour on the server to introduce their own cache. Posthog will ignore that cache by default, as this is also NextJS's default behavior to any fetch call.

You can override that configuration when initializing Posthog if you wish, but make sure you understand the pros/cons of using NextJS's cache and are aware that you might get cached results rather than the actual result our server would be returning - for feature flags, for example.

TSX

posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
  // ... your configuration
  fetch_options: {
    cache: 'force-cache', // Use NextJS cache
    next_options: {       // Passed to the `next` option for `fetch`
      revalidate: 60,     // Cache for 60 seconds
      tags: ['posthog'],  // Can be used with NextJS `revalidateTag` function
    },
  }
})

Configuring a reverse proxy to PostHog
To improve the reliability of client-side tracking and make requests less likely to be intercepted by tracking blockers, you can setup a reverse proxy in Next.js. Read more about deploying a reverse proxy using Next.js rewrites, Next.js middleware, and Vercel rewrites.


Frequently asked questions

Does wrapping my app in the PostHog provider de-opt it to client-side rendering?
No. Even though the PostHog provider is a client component, since we pass the children prop to it, any component inside the children tree can still be a server component. Next.js creates a boundary between server-run and client-run code.

The use client reference says that it "defines the boundary between server and client code on the module dependency tree, not the render tree." It also says that "During render, the framework will server-render the root component and continue through the render tree, opting-out of evaluating any code imported from client-marked code."

Pages router components are client components by default.


What does wrapping my app in the PostHog provider do?
On top of the standard features like autocapture, custom events, session recording, and more, wrapping your app in the PostHog provider gives you:

The usePostHog, useFeatureFlagEnabled, and other hooks in any component.
A PostHog context you can access in any component.
The <PostHogFeature> component which simplifies feature flag logic.
See the React SDK docs for more details.


Why use a useEffect hook to initialize PostHog?
We want to initialize PostHog when the app is loaded. The React docs recommend using a useEffect hook to do this:

Effects let you specify side effects that are caused by rendering itself, rather than by a particular event.

Technically, you can also use a window object check to initialize PostHog. This happens outside the React lifecycle, meaning it happens earlier and it looks like this:

JavaScript
TSX

// app/providers.js
'use client'
import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'

if (typeof window !== 'undefined') {
  posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
    capture_pageview: false // Disable automatic pageview capture, as we capture manually
  })
}

export function PHProvider({ children }) {
  return <PostHogProvider client={posthog}>{children}</PostHogProvider>
}
The problem with this is that it can cause a hydration and/or mismatch error like Warning: Prop dangerouslySetInnerHTML did not match..


Why does the pageview component need a useEffect?
Using a useEffect hook is the simplest way to accurately capture pageviews. Other approaches include:

Not using a useEffect hook, but this might lead to duplicate page views being tracked if the component re-renders for reasons other than navigation. It might work depending on your implementation.
Using window.navigation to track pageviews, but this approach is more complex and is not supported in all browsers.
"""
)