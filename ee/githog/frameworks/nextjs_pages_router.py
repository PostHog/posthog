import fnmatch
from typing import List

from .config import GitHogFrameworkConfig, GitHogFrameworkName


def detect_nextjs_pages_router(all_files: List[str]) -> bool:

    has_pages_app = any(fnmatch.fnmatch(file, "pages/_app.*") for file in all_files)

    has_app_layout = any(fnmatch.fnmatch(file, "app/layout.*") for file in all_files)
    
    if has_pages_app and not (has_app_layout):
        return True
    return False

NEXTJS_PAGES_ROUTER_CONFIG = GitHogFrameworkConfig(
    name=GitHogFrameworkName.NEXTJS_PAGES_ROUTER,
    detect=detect_nextjs_pages_router,
    filter_patterns=['*.js', '*.jsx', '*.ts', '*.tsx'],
    include_patterns=["package.json"],
    ignore_patterns=["node_modules/*", "dist/*", ".git/*", ".github/*", "*.md", "LICENSE"],
    create_patterns=['.env.example'],
    pr_instructions="""
1. To finish integrating PostHog into your Next.js app, you need to run `npm / yarn / pnpm install` to update your lockfile.
2. Add NEXT_PUBLIC_POSTHOG_KEY=your-posthog-api-key to your environment variables - you can find this in your PostHog project settings.
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
If you use the pages router, you can integrate PostHog at the root of your app in pages/_app.js. Because Next.js is a single page app, you need to capture $pageview events manually too.

JavaScript

// pages/_app.js
import { useEffect } from 'react'
import { Router } from 'next/router'
import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'

export default function App({ Component, pageProps }) {

  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com',
      // Enable debug mode in development
      loaded: (posthog) => {
        if (process.env.NODE_ENV === 'development') posthog.debug()
      }
    })

    const handleRouteChange = () => posthog?.capture('$pageview')

    Router.events.on('routeChangeComplete', handleRouteChange);

    return () => {
      Router.events.off('routeChangeComplete', handleRouteChange);
    }
  }, [])

  return (
    <PostHogProvider client={posthog}>
      <Component {...pageProps} />
    </PostHogProvider>
  )
}
Note: Unlike the app router, we don't set capture_pageview to false in the initialization because we need it to capture the initial pageview.


Pageleave events (optional)
To capture $pageleave events accurately, set up useRef and useRouter to track the URL and capture a $pageleave event with it on routeChangeStart.

JavaScript

// pages/_app.js
import { useEffect, useRef } from 'react'
import { Router, useRouter } from 'next/router'
import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'

export default function App({ Component, pageProps }) {

  const router = useRouter()
  const oldUrlRef = useRef('')

  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com',
      // Enable debug mode in development
      loaded: (posthog) => {
        if (process.env.NODE_ENV === 'development') posthog.debug()
      }
    })

    const handleRouteChange = () => posthog?.capture('$pageview')

    const handleRouteChangeStart = () => posthog?.capture('$pageleave', {
      $current_url: oldUrlRef.current
    })

    Router.events.on('routeChangeComplete', handleRouteChange);
    Router.events.on('routeChangeStart', handleRouteChangeStart);

    return () => {
      Router.events.off('routeChangeComplete', handleRouteChange);
      Router.events.off('routeChangeStart', handleRouteChangeStart);
    }
  }, [])

  return (
    <PostHogProvider client={posthog}>
      <Component {...pageProps} />
    </PostHogProvider>
  )
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
For the pages router, we can use the getServerSideProps function to access PostHog on the server-side, send events, evaluate feature flags, and more.

This looks like this:

JavaScript

// pages/posts/[id].js
import { useContext, useEffect, useState } from 'react'
import { getServerSession } from "next-auth/next"
import { PostHog } from 'posthog-node'

export default function Post({ post, flags }) {
  const [ctaState, setCtaState] = useState()

  useEffect(() => {
    if (flags) {
      setCtaState(flags['blog-cta'])
    }
  })

  return (
    <div>
      <h1>{post.title}</h1>
      <p>By: {post.author}</p>
      <p>{post.content}</p>
      {ctaState &&
        <p><a href="/">Go to PostHog</a></p>
      }
      <button onClick={likePost}>Like</button>
    </div>
  )
}

export async function getServerSideProps(ctx) {

  const session = await getServerSession(ctx.req, ctx.res)
  let flags = null

  if (session) {
    const client = new PostHog(
      process.env.NEXT_PUBLIC_POSTHOG_KEY,
      {
        host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
      }
    )

    flags = await client.getAllFlags(session.user.email);
    client.capture({
      distinctId: session.user.email,
      event: 'loaded blog article',
      properties: {
        $current_url: ctx.req.url,
      },
    });

    await client.shutdown()
  }

  const { posts } = await import('../../blog.json')
  const post = posts.find((post) => post.id.toString() === ctx.params.id)
  return {
    props: {
      post,
      flags
    },
  }
}
Note: Make sure to always call await client.shutdown() after sending events from the server-side. PostHog queues events into larger batches, and this call forces all batched events to be flushed immediately.


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

// app/providers.tsx
'use client'
import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'

if (typeof window !== 'undefined') {
  posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
    capture_pageview: false // Disable automatic pageview capture, as we capture manually
  })
}

export function PHProvider({
  children,
}: {
  children: React.ReactNode
}) {
  return <PostHogProvider client={posthog}>{children}</PostHogProvider>
}
The problem with this is that it can cause a hydration and/or mismatch error like Warning: Prop dangerouslySetInnerHTML did not match..


Why does the pageview component need a useEffect?
Using a useEffect hook is the simplest way to accurately capture pageviews. Other approaches include:

Not using a useEffect hook, but this might lead to duplicate page views being tracked if the component re-renders for reasons other than navigation. It might work depending on your implementation.
Using window.navigation to track pageviews, but this approach is more complex and is not supported in all browsers.
"""
)