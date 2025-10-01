<img src="https://github.com/PostHog/livestream/assets/391319/d4a4964d-4b19-4605-b268-157366817863" width="280" height="280" />

# RealTime Hog 3000

The start of something fresh.

Hog 3000 powers live event stream on PostHog: https://us.posthog.com/project/0/activity/live

## Endpoints

- `/` - dummy placeholder
- `/served` - total number of events and users recorded
- `/stats` - number of unique users (distinct id) on a page
- `/events` - stream consumed events to the requester, it's a done through
   [Server Side Event](sse-moz), it supports extra query params adding filters:
  - `eventType` - event type name,
  - `distinctId` - only events with a given distinctId,
  - `geo` - return only coordinates guessed based on IP,
- `/debug` - dummy html for SSE testing,
- `/debug/sse/` - backend for `/debug` generating a server side events,
- `/metrics` - exposes metrics in Prometheus format

## Installing

One needs a IP -> (lat,lng) database:

```bash
curl https://mmdbcdn.posthog.net/ | brotli -d > mmdb.db
```

Config the configs in `configs/config.yml`. You can take a peak at the examples in `configs/configs.example.yml`

Run it!

```bash
go run .
```

## Notice

If modifying fields with `//easyjson:json` comment, one must regenerate the easyjson marshaller / unmarshaller.
It requires to install: `go install github.com/mailru/easyjson/...@latest`
