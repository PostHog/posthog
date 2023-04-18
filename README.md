# capture

This is a rewrite of [capture.py](https://github.com/PostHog/posthog/blob/master/posthog/api/capture.py), in Rust.

## Why?

Capture is very simple. It takes some JSON, checks a key in Redis, and then pushes onto Kafka. It's mostly IO bound.

We currently use far too much compute to run this service, and it could be more efficient. This effort should not take too long to complete, but should massively reduce our CPU usage - and therefore spend.

## How?

I'm trying to ensure the rewrite at least vaguely resembles the Python version. This will both minimize accidental regressions, but also serve as a "rosetta stone" for engineers at PostHog who have not written Rust before.
