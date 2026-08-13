# The image fetch lane

This lane downloads the remote images that a session replay refers to, so the scrub lane can
remove private data from them and the result can train a model.

It is a web crawler. The names here are the crawler's names, and this file is the specification the
code is written against. Where the code and this file disagree, one of them is a bug.

## The model

| Part               | What it is                                                                                                                       |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Frontier           | The topic `session_replay_image_fetch`. It holds the URLs waiting to be fetched.                                                 |
| Back queue         | The URLs of one registrable domain. The topic key is the domain, so a partition holds whole back queues.                         |
| Crawl history      | The Redis record of the URLs this lane has finished with, whatever the outcome. It answers the URL-seen test.                    |
| Host budget        | The rate limit, connection limit, and circuit breaker for one registrable domain.                                                |
| Hop budget         | The number of moves one URL may make before the lane gives up.                                                                   |
| Registrable domain | The operator boundary, from the public suffix list. `example.com` for `img1.cdn.example.com`, but `myapp.vercel.app` for itself. |

A redirect to another domain is a new candidate URL. It goes back through the frontier rather than
being fetched in place, because the budget that governs it belongs to whichever consumer owns that
domain's partition.

## Limits

| Constant                                | Scope                                             | Value      |
| --------------------------------------- | ------------------------------------------------- | ---------- |
| Requests in flight                      | pod                                               | 300        |
| Requests in flight per domain           | domain                                            | 6          |
| Requests per second per domain          | domain                                            | 1, burst 5 |
| Hop budget                              | one original URL, across every message it becomes | 10         |
| Redirects followed without republishing | one fetch                                         | 3          |
| Response bytes                          | one response                                      | 2 MB       |
| Request timeout                         | one URL, redirects included                       | 10 seconds |
| Pass deadline                           | one batch                                         | 20 seconds |
| Domains tracked                         | pod                                               | 20000      |

Every back queue runs at the same time. This is how the pod reaches its limit rather than a
fairness rule: one domain holds at most 6 requests, so about 50 domains must be active together to
use 300.

A wait costs nothing, so it does not count as in flight. Only a request holding a socket counts.

## Requirements

Each of these is numbered so a test can name the one it covers.

### Limits

1. Requests in flight never exceed the pod limit.
2. Requests in flight to one domain never exceed the domain limit, redirects included.
3. Requests to one domain never exceed its rate.
4. A redirect is not a way around either limit.
5. After any wait, a request checks again before it goes out. The domain must not be blocked, and
   the batch deadline must not have passed. A grant that went stale during the wait is returned,
   not sent.

### Redirects

6. The lane follows a redirect that stays on the same domain, up to the limit.
7. The lane publishes a redirect that leaves the domain back to the frontier, keyed by the new
   domain.
8. Every redirect target passes the URL policy again: public host, scheme, length, and the SSRF
   checks in `common/utils/request.ts`.
9. The lane never follows a redirect from HTTPS to plain HTTP.
10. A republished message carries the original ref. The recording points at that ref, and a hash of
    the redirect target matches nothing.

### Hops and retries share one budget

11. Every message carries a hop budget. A same-domain redirect, a republish, and a retry each spend
    one.
12. When the budget reaches zero, the lane writes the crawl history and stops.
13. Only a transient failure spends a hop on a retry: a timeout, a connection error, a 429, a 503,
    or a refusal by the budget. A 404 and a 403 are answers.
14. A retry is a publish to a delay topic. The lane does not sleep and try again in place.
15. Every message carries the earliest time to try again.

### What the lane learns about a site

16. One network failure for a domain applies to every URL queued for that domain in the same pass.
17. A `Retry-After` header holds the whole domain for the period it names.
18. Repeated failures open the circuit breaker for the domain, and its cooldown grows each time.
19. This knowledge lives in the pod that owns the partition. It does not cross pods, and a
    rebalance loses it.

### Order, offsets, and termination

20. The lane does not need per-key order. Images have no order between them.
21. An offset commits only after the work behind it is durable: fetched and recorded, republished,
    or given up.
22. A duplicate is acceptable. The crawl history absorbs it.
23. A message that does not parse is counted and dropped. There is no dead letter topic: the lane
    cannot record what it cannot read, and replaying it helps nobody until the format disagreement
    is fixed.
24. A URL the lane gives up on goes into the crawl history, so it stops coming back.

### What we must be able to see

25. Requests by outcome, and refusals by reason. No team label on these.
26. The hops a URL took, and the time it spent in the system.
27. The rate of republishing, so amplification is visible.
28. Requests in flight, and the domains that are blocked.
29. The busiest teams, as a bounded top N with an `other` bucket.
30. The number of distinct teams, as one gauge.
31. No metric carries a URL, and no metric carries an unbounded team label. The team ID space is in
    the low millions, so a `team_id` label on a per-request metric is unbounded both in the time
    series database and in the memory of the pod exporting it.

## How a message waits

Kafka has no delayed delivery. The delay belongs to the topic, not to the message, because a
message that waits an hour would otherwise sit in front of one that waits a minute.

```text
session_replay_image_fetch_retry_1m
session_replay_image_fetch_retry_10m
session_replay_image_fetch_retry_1h
```

Every message in one topic waits the same period, so they arrive in the order they become ready.
The consumer reads the first message, waits out the remainder, and publishes it back to the
frontier. A message needing longer than an hour goes around the 1h topic again and spends a hop.

Three things follow. Each one stops the design from working if it is missed.

**The consumer of a long topic must outlive `max.poll.interval.ms`.** That value is 300 seconds. A
consumer that sleeps for 10 minutes is evicted, and its partition is replayed by a consumer that
will sleep just as long. Raise it per consumer group: 900000 for the 10m topic, 4200000 for the 1h
topic.

**A sleeping consumer must keep reporting itself healthy.** The health check fails a consumer that
has not called `heartbeat()` for 60 seconds. Pump it on a timer for the whole wait.

**Lag on a delay topic is the design working.** A 1h topic reports an hour of lag whenever it holds
anything. Alert on the age of the oldest message passing the topic's period by a wide margin, which
means the consumer stopped. Do not alert on lag.

Each delay consumer runs `minPods: 0` and `maxPods: 1`. The maximum of one matters: a lag trigger
assumes more consumers drain a topic faster, and that is false here. These messages are waiting on
purpose. A tier holding thousands of them would otherwise scale to dozens of pods, none of which
can make a message ripen sooner.

## Why a retry is necessary at all

The mirror keeps a cache of the refs it has published, 500000 per pod, and does not produce a ref
twice while it is cached. So a URL that fails, and that this lane does not write to the crawl
history, does not come back until that entry leaves the cache.

An earlier version of this lane treated an absent crawl history entry as a retry. It is a loss.

## What is not built

The requirements above are the target. These parts of them have no implementation yet, and the
code is the authority until they do.

**Nothing publishes to the frontier or to a delay topic.** `FrontierPublisher` exists and is
tested, and the delay consumers exist and are registered, but no caller wires them together. So
requirements 7 and 11 to 15 are unmet: a cross-domain redirect is followed in place rather than
republished, a transient failure is dropped rather than retried, and no hop is ever spent.
Requirement 24 follows: a URL the lane gives up on gets no crawl history entry, which is the loss
the section above describes.

**`notBeforeMs` is parsed and ignored.** A record that arrives early is fetched anyway. The host
budget refuses it without sending, so the effect today is a wasted read rather than a rude request.

**Requirement 8 is partly met.** A redirect target is checked for scheme, an HTTPS downgrade, and
userinfo, and every hop re-enters the SSRF checks. It is not checked against the public-host rule
or the length limit that the first candidate passed.

**Requirements 29 and 30 have no metrics.** There is no per-team view. Requirement 31 holds only
because nothing team-aware exists to break it.

**No counter across pods.** A rebalance can put two pods on one domain for a few seconds, and the
rate doubles for that long.

**No robots.txt.** The lane cannot leave dry run until it reads one.

**No produce to the scrub topic.** The bytes are counted and dropped.
