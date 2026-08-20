# The image fetch lane

This lane downloads the remote images that a session replay refers to, so the scrub lane can
remove private data from them and the result can train a model.

It is a web crawler. The names here are the crawler's names, and this file is the specification the
code is written against. Where the code and this file disagree, one of them is a bug.

## The model

| Part               | What it is                                                                                                                                                                                                                        |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Mirror             | The upstream lane. It keeps the media placeholder, writes the image URL ref into a `data-anon-image-ref-<attribute>` sibling, and publishes the URLs it collected to the frontier.                                                |
| Ref                | What the mirror writes into the namespaced sibling attribute, built from a hash of the image URL. It is how a fetched image is later matched back to the recording that wanted it.                                                |
| Frontier           | The topic `session_replay_image_fetch`. It holds the URLs waiting to be fetched.                                                                                                                                                  |
| Back queue         | The URLs of one registrable domain. The topic key is the domain, so a partition holds whole back queues.                                                                                                                          |
| Pass               | The fetching for one Kafka poll batch. Every back queue in the batch runs at the same time, and wall time bounds the pass rather than work.                                                                                       |
| Crawl history      | The shared record of URLs this lane has finished with, whatever the outcome. A table setting selects DynamoDB; otherwise the lane uses Redis.                                                                                     |
| Host budget        | The token bucket, connection limit, and circuit breaker for one registrable domain. The rate moves by AIMD: a failure halves it, and success raises it slowly.                                                                    |
| Hop                | One trip a URL makes back through Kafka. The lane spends a hop when it puts a URL back: a retry, a redirect that left the domain, or a URL that arrived before its wait ended. A redirect the lane follows in place costs no hop. |
| Hop budget         | The number of hops one URL may make before the lane gives up.                                                                                                                                                                     |
| Registrable domain | The operator boundary, from the Public Suffix List. Also called eTLD+1. `example.com` for `img1.cdn.example.com`, but `myapp.vercel.app` for itself.                                                                              |

A redirect to another domain is a new candidate URL. It goes back through the frontier rather than
being fetched in place, because the budget that governs it belongs to whichever consumer owns that
domain's partition.

The lane reads the crawl history after parsing and in-batch deduplication. It makes fetch decisions
from the result, then writes completed URLs at the end of the Kafka batch. The DynamoDB backend uses
batch operations with service limits of 100 reads and 25 writes. An expired row counts as absent
before DynamoDB removes it. Before Kafka consumption starts, the lane writes and consistently reads
a short-lived probe record so that a missing table or IAM permission stops the pod.

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
| Pass deadline                           | one pass                                          | 20 seconds |
| Pass wall time, worst case              | one pass                                          | 30 seconds |
| Domains tracked                         | pod                                               | 20000      |

Every back queue runs at the same time. This is how the pod reaches its limit rather than a
fairness rule: one domain holds at most 6 requests, so about 50 domains must be active together to
use 300.

Only a request holding a socket counts as in flight. A URL waiting for its domain's rate limit
holds nothing, so it is not counted. A wait between the hops of one redirect chain is counted,
because the request is already open.

The pass deadline decides whether a request starts. It never decides how long that request may
take. A request cut short by the pass clock would time out through no fault of the site, and the
budget would read that as the site failing. So a request that starts just inside the deadline still
gets its whole timeout, and one pass can run to the deadline plus one request timeout. That is the
worst case in the table, and it stays well inside Kafka's `max.poll.interval.ms` of 300 seconds.

## Requirements

Each of these is numbered so a test can name the one it covers.

### Limits

1. Requests in flight never exceed the pod limit.
2. Requests in flight to one domain never exceed the domain limit, redirects included.
3. Requests to one domain never exceed the rate its token bucket allows.
4. A redirect is not a way around either limit.
5. After any wait, a request checks again before it goes out. The domain must not be blocked, and
   the pass deadline must not have passed. A grant that went stale during the wait is returned,
   not sent.

### Redirects

6. The lane follows a redirect that stays on the same domain, up to the limit.
7. The lane publishes a redirect that leaves the domain back to the frontier, keyed by the new
   domain.
8. Every redirect target passes the same checks the first candidate passed. See "Security: what we
   never connect to".
9. The lane never follows a redirect from HTTPS to plain HTTP.
10. A republished message carries the original ref. The ref is a hash of the original URL, so a ref
    built from a redirect target matches nothing in the recording that wanted the image.

### Hops and retries share one budget

11. Every message carries a hop budget. A republish and a retry each spend one. A redirect that
    stays on the same domain is bounded separately, by the redirect limit of one fetch, so a chain
    is bounded by the two limits together rather than by the budget alone.
12. When the budget reaches zero, the lane writes the crawl history and stops.
13. Only a transient failure spends a hop on a retry: a timeout, a connection error, HTTP 429, HTTP
    503, or a refusal by the host budget. HTTP 404 and HTTP 403 are answers.
14. A retry is a publish to a delay topic. The lane does not sleep and try again in place.
15. Every message carries the earliest time to try again.

### Host budget: what the lane learns about a site

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

**Keeping one record uncommitted means restarting the pod.** Kafka commits one offset for each
partition, and that offset is a high water mark. Committing it commits every record below it, so a
consumer cannot hold one record back and commit the ones around it. A consumer that must not commit
a record has one move, which is to throw. The throw leaves the poll loop and the pod shuts down.
Kubernetes starts it again, and the new pod reads the batch from the last committed offset.

The lane spends that on one condition: a Kafka produce that failed. It is the only case where the
lane took a URL out of the frontier and put nothing back, so no copy of that URL is left anywhere.
It is also usually brief, so the pod that comes back is likely to get the record through.

A crawl history read the store could not answer loses URLs the same way, and the lane commits it
regardless. A store that cannot answer this batch cannot answer the next one either, so throwing
would restart the pod on every batch and fetch nothing at all. The lane leaves those URLs
unrecorded, so the mirror offers them again the next time a session refers to the same image. A
counter records each one, which keeps the loss visible.

**Rule 21 is about URLs the lane got an answer for.** The fetch pass returns an outcome for every
URL it is given, so an exception out of the pass is a fault in our own code rather than something a
site did. The consumer counts it, drops the batch, and lets the offset commit. A replay would run
the same code over the same records and meet the same fault, which stops the partition instead of
clearing it.

### Metrics

25. Requests by outcome, and refusals by reason. No team label on these.
26. The hops a URL took, and the time it spent in the system.
27. The rate of republishing, so amplification is visible.
28. Requests in flight, and the domains that are blocked.
29. The busiest teams, as a bounded top N with an `other` bucket, using the Space-Saving algorithm
    for heavy hitters. Nothing on this path holds the team ID, so a team here is the pseudonym the
    mirror sends.
30. The number of distinct teams, as one gauge, estimated with HyperLogLog.
31. No metric carries a URL, and no metric carries an unbounded team label. The team ID space is in
    the low millions, so a `team_id` label on a per-request metric is unbounded both in the time
    series database and in the memory of the pod exporting it.

### Security: what we never connect to

These rules exist to stop server-side request forgery. The URLs come from a page the lane did not
write, so an attacker chooses them, and the request leaves from inside our network.

32. The lane must never connect to an IP address that is not globally routable. That covers
    loopback, the RFC 1918 private ranges, link-local, carrier-grade NAT, multicast, and the
    reserved ranges, in IPv4 and IPv6. Smokescreen, the egress proxy, enforces this in production.
    `httpStaticLookup`, our DNS hook for undici, enforces it when no proxy is set.
33. The check must use the same DNS answer as the connection, so that DNS rebinding cannot slip an
    IP address past it. An attacker who owns a name can return a different IP address on every
    lookup. Code that resolves a name, checks the IP address, then hands the name to something that
    resolves it again has checked one address and connected to another.
34. The collector, which is the URL policy the mirror runs before it publishes, drops a URL that a
    later check would refuse, so it never reaches the topic. It drops four kinds: a host that is not
    public, a scheme that is not HTTPS, a port that the scheme does not own, and a URL that is too
    long.
35. Every check in rule 34 runs again in the lane, on the first URL and on every redirect target.
    The network layer performs none of them. Smokescreen limits which IP addresses we reach, not
    which service we reach at those addresses.

Neither implementation passes a name onward, which is what satisfies rule 33. Smokescreen resolves
the name, checks the IP addresses it got, and connects to one of those. `httpStaticLookup` resolves
the name, checks the IP addresses it got, and hands that list to undici, which connects to them.

The lane repeats the collector's checks because nothing below the lane performs them. Smokescreen
sees an IP address, not a scheme, a port, or a hostname, so the collector and the lane are the only
two places these run, and the two must agree. Both allow HTTPS on port 443 and nothing else.

The host check is the one that needs both layers. An IP address check at connect time refuses a
private address, so it covers `169.254.169.254`, the cloud instance metadata endpoint. It cannot
refuse `wiki.corp`, because that hostname looks ordinary and its DNS answer can be a globally
routable address. Only a check on the hostname itself refuses that.

A hostname the attacker owns can still reach any globally routable IP address on port 443, and the
outcome metric shows whether something answered. Any port scanner learns the same thing for less
effort, so the cost to us is our reputation rather than leaked data: the request leaves our egress
IP addresses, not a customer's. The per-domain token bucket holds it to one request each second.

### Smokescreen

`PostHog/smokescreen` is a small wrapper around `stripe/smokescreen`. Two settings matter here.

Its ACL is `action: open`, so it allows every domain. That is what this lane needs, because a
customer's images can sit on any host.

Its private IP address blocking is on. The deployment passes no `--unsafe-allow-private-ranges`,
and that flag is the only way to turn the blocking off.

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

That figure holds only because a batch carries one record. A batch of several is held one record at
a time, and a delay topic can hold records written hours apart, so each would wait its own period
inside one batch. The server refuses to start with any other batch size, and refuses to start
against any topic other than the three the publisher writes to.

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
purpose. A delay topic holding thousands of them would otherwise scale to dozens of pods, none of
which can make a message become ready sooner.

## Why a retry is necessary at all

The mirror keeps a cache of the refs it has published, 500,000 per pod, and does not produce a ref
twice while it is cached. So a URL that fails, and that this lane does not write to the crawl
history, does not come back until that entry leaves the cache.

An earlier version of this lane treated an absent crawl history entry as a retry. It is a loss.

## Dry run

The lane runs every decision that needs no request, and sends none. It parses the records, applies
the age limit and all three layers of dedup (within the batch, within the pod, and against the
crawl history), and writes the crawl history. What it would have
fetched is counted as `fetchable`, which is the offered request rate.

The host budget belongs to the fetch pass, which dry run does not build. So the gauges of rule 28
report zero, which is what a lane holding no request and blocking no domain should report.

This is the mode phase 0 measures in. The server refuses to clear the flag, and names the two things
that must land before it can: reading robots.txt, and producing the image to the scrub topic.
