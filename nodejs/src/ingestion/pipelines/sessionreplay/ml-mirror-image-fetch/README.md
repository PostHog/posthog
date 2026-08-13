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
| Pass wall time, worst case              | one batch                                         | 30 seconds |
| Domains tracked                         | pod                                               | 20000      |

Every back queue runs at the same time. This is how the pod reaches its limit rather than a
fairness rule: one domain holds at most 6 requests, so about 50 domains must be active together to
use 300.

Only a request holding a socket counts as in flight. A URL waiting for its domain's rate limit
holds nothing, so it is not counted. A wait between the hops of one redirect chain is counted,
because the request is already open.

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
8. Every redirect target passes the same checks the first candidate passed. See "What we never
   connect to".
9. The lane never follows a redirect from HTTPS to plain HTTP.
10. A republished message carries the original ref. The recording points at that ref, and a hash of
    the redirect target matches nothing.

### Hops and retries share one budget

11. Every message carries a hop budget. A republish and a retry each spend one. A redirect that
    stays on the same domain is bounded separately, by the redirect limit of one fetch, so a chain
    is bounded by the two limits together rather than by the budget alone.
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

**Rule 21 covers the URLs the lane handled.** The fetch pass answers with an outcome for every URL,
so a throw out of the pass is a defect in our own code rather than an answer about a URL. The
consumer counts that throw, drops the batch, and commits it. A replay would meet the same defect on
every read and stop the partition rather than recover it.

**Holding a batch costs the pod.** There is no way to refuse one offset and commit the rest, so a
consumer that must hold a batch throws, and a throw out of the poll loop shuts the pod down.
Kubernetes restarts it and the batch replays.

Only a failed Kafka produce is worth that. It is the one case where the lane took a URL out of the
frontier and put nothing back, and it usually clears on the next attempt.

A crawl history read that the store cannot answer is not worth it. The store answers nothing for
the next batch either, so the pod would restart on every batch and make no progress. Those URLs are
left unrecorded instead, and the mirror offers them again when a session refers to the same image.
The read errors are counted, so the loss is visible.

### What we must be able to see

25. Requests by outcome, and refusals by reason. No team label on these.
26. The hops a URL took, and the time it spent in the system.
27. The rate of republishing, so amplification is visible.
28. Requests in flight, and the domains that are blocked.
29. The busiest teams, as a bounded top N with an `other` bucket. Nothing on this path holds the
    team ID, so a team here is the pseudonym the mirror sends.
30. The number of distinct teams, as one gauge.
31. No metric carries a URL, and no metric carries an unbounded team label. The team ID space is in
    the low millions, so a `team_id` label on a per-request metric is unbounded both in the time
    series database and in the memory of the pod exporting it.

### What we never connect to

32. The lane must never connect to a private address. This covers loopback, link-local, and every
    other range that is not public. Smokescreen does this in production. `httpStaticLookup` does it
    when no proxy is set.
33. The check must use the same DNS answer as the connection.
34. The collector drops a URL that a later check would refuse, so it never reaches the topic. It
    drops four kinds: a host that is not public, a scheme that is not HTTPS, a port that the scheme
    does not own, and a URL that is too long.
35. Every check in rule 34 runs again in the lane, on the first URL and on every redirect target.
    The network layer performs none of them. Smokescreen limits which addresses we reach, not which
    service we reach at those addresses.

**Rule 33 is the one that is easy to get wrong.** One name can give a different address each time
someone looks it up. The attacker owns the name, so the attacker chooses those addresses. Now
suppose we look up the name, check the address, and then hand the name to something that looks it up
again. The second lookup can return an address we never saw. We connect to that one.

So a check is only worth something when the thing that checks the address is also the thing that
opens the connection. Both of ours work that way:

- Smokescreen looks up the name, checks what it got, and connects to that.
- `httpStaticLookup` looks up the name, checks what it got, and hands those addresses to undici,
  which connects to them.

**The lane repeats the collector's checks because nothing below the lane performs them.**
Smokescreen sees an address, not a scheme, a port, or a name. So the collector and the lane are the
only two places these run, and the two must agree. Both allow HTTPS on the scheme's own port and
nothing else.

The host check is the one worth stating plainly. An address check at connect time refuses a private
address, so it covers `169.254.169.254`. It cannot refuse `wiki.corp`, because the name looks
ordinary and its DNS answer can be a public address. Only a check on the name itself refuses that,
and the collector and the lane both perform one.

**A name the attacker owns can still reach any public address on port 443.** We connect, and the
outcome metric shows whether something answered. Any port scanner learns the same thing for less
effort. The cost to us is different. The request comes from our egress addresses, not from a
customer. So this is a question of our reputation rather than of leaked data. The per-domain rate limit
holds it to one request each second.

### Smokescreen

`PostHog/smokescreen` is a small wrapper around `stripe/smokescreen`. Two settings matter here.

Its ACL is `action: open`, so it allows every domain. That is what this lane needs, because a
customer's images can sit on any host.

Its private-address blocking is on. The deployment passes no `--unsafe-allow-private-ranges`, and
that flag is the only way to turn the blocking off.

The ACL says nothing about ports, which is why rule 35 exists.

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

**The consumer of a long topic must outlive `max.poll.interval.ms`.** The shared default is 300
seconds. A consumer that sleeps for 10 minutes is evicted, and its partition is replayed by a
consumer that will sleep just as long. The retry server therefore sets the value itself, as the
period of its topic plus one minute, rather than leaving it to the deployment.

**A sleeping consumer must keep reporting itself healthy.** It calls
`KafkaConsumer.reportDeliberateWait()`, which moves the loop clock as well as the heartbeat clock.
That is separate from `heartbeat()` on purpose: two lanes drive `heartbeat()` from a timer, and a
timer keeps firing while a batch is wedged, so relaxing the stall detector there would leave a stuck
pod reporting healthy forever.

**Lag on a delay topic is the design working.** A 1h topic reports an hour of lag whenever it holds
anything. Alert on the age of the oldest message passing the topic's period by a wide margin, which
means the consumer stopped. Do not alert on lag.

Each delay consumer runs `minPods: 0` and `maxPods: 1`. The maximum of one matters: a lag trigger
assumes more consumers drain a topic faster, and that is false here. These messages are waiting on
purpose. A tier holding thousands of them would otherwise scale to dozens of pods, none of which
can make a message become ready sooner.

## Why a retry is necessary at all

The mirror keeps a cache of the refs it has published, 500000 per pod, and does not produce a ref
twice while it is cached. So a URL that fails, and that this lane does not write to the crawl
history, does not come back until that entry leaves the cache.

An earlier version of this lane treated an absent crawl history entry as a retry. It is a loss.

## Dry run

The lane runs every decision that needs no request, and sends none. It parses the records, applies
the age limit and all three layers of dedup, and writes the crawl history. What it would have
fetched is counted as `fetchable`, which is the offered request rate.

The host budget belongs to the fetch pass, which dry run does not build. So the gauges of rule 28
report zero, which is what a lane holding no request and blocking no domain should report.

This is the mode phase 0 measures in. The server refuses to clear the flag, and names the two things
that must land before it can: reading robots.txt, and producing the image to the scrub topic.
