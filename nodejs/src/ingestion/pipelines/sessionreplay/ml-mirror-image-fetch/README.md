# The image fetch lane

This lane downloads the remote images that a session replay refers to, so the scrub lane can
remove private data from them and the result can train a model.

It is a web crawler. The names here are the crawler's names, and this file is the specification the
code is written against. Where the code and this file disagree, one of them is a bug.

## Principles

- The image fetcher is open source, this README is publicly visible, and everything we are doing is in the open and fully transparent
- Any time there is ambiguity, we should resolve it in the direction of not fetching the image
- We only fetch images that are linked to by a Session Replay from a customer with AI training enabled, and respect known methods for web sites to opt out of this fetching, regardless of whether there is a legal requirement to do so
- We have a high standard for politeness, and have aggressive rate limits to enforce this
- We combine many opt out signals, any one of them causes us to stop fetching. We pick the order that these are checked to prioritise legal requirements first, spec compliance second, and load on hosts third

## The model

| Part               | What it is                                                                                                                                                                                                                        |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Mirror             | The upstream lane. It replaces each image in a recording with a ref, and publishes the URLs it collected to the frontier.                                                                                                         |
| Ref                | What the mirror writes into the recording in place of an image, built from a hash of the image URL. It is how a fetched image is later matched back to the recording that wanted it.                                              |
| Frontier           | The topic `session_replay_image_fetch`. It holds the URLs waiting to be fetched.                                                                                                                                                  |
| Back queue         | The URLs of one registrable domain. The topic key is the domain, so a partition holds whole back queues.                                                                                                                          |
| Pass               | The fetching for one Kafka poll batch. Every back queue in the batch runs at the same time, and wall time bounds the pass rather than work.                                                                                       |
| Crawl history      | The Redis record of the URLs this lane has finished with, whatever the outcome. It answers the URL-seen test.                                                                                                                     |
| Host budget        | The token bucket, connection limit, and circuit breaker for one registrable domain. The rate moves by AIMD: a failure halves it, and success raises it slowly.                                                                    |
| Hop                | One trip a URL makes back through Kafka. The lane spends a hop when it puts a URL back: a retry, a redirect that left the domain, or a URL that arrived before its wait ended. A redirect the lane follows in place costs no hop. |
| Hop budget         | The number of hops one URL may make before the lane gives up.                                                                                                                                                                     |
| Registrable domain | The operator boundary, from the Public Suffix List. Also called eTLD+1. `example.com` for `img1.cdn.example.com`, but `myapp.vercel.app` for itself.                                                                              |

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
| Pass deadline                           | one pass                                          | 20 seconds |
| Pass wall time, worst case              | one pass                                          | 30 seconds |
| Domains tracked                         | pod                                               | 20000      |
| Crawl history entry                     | one URL, one team                                 | 30 days    |

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

These limits count every request the lane makes, not only a request for an image. A file the lane
reads to decide whether it may fetch at all, such as robots.txt, spends the same budget as the image
would. A host feels those requests the same way.

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
10. A republished message carries the original ref. The ref is a hash of the original URL. A ref
    built from a redirect target matches no recording.

### Hops and retries share one budget

11. Every message carries a hop budget. A republish and a retry each spend one hop. A redirect that
    stays on the same domain spends no hop. The redirect limit of one fetch bounds those instead, so
    two limits bound a chain rather than one.
12. A URL can spend its whole hop budget without an answer. The lane then makes no further attempt
    on it, and writes it to the crawl history under rule 24.
13. Only a transient failure spends a hop on a retry. A transient failure is a timeout, a connection
    error, HTTP 429, HTTP 503, or a refusal by the host budget. HTTP 404 and HTTP 403 are answers.
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
23. The lane counts a message it cannot parse, and drops it. There is no dead letter topic. The lane
    cannot record a URL it cannot read, and a replay gives the same result until someone fixes the format.
24. The lane writes a URL to the crawl history when it has an answer for that URL. An answer is a
    fetched image, a refusal such as a 404 or a 403, or a hop budget the URL spent in full. The lane
    reads that entry before a later fetch, and does not request the URL again while the entry lives.

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
29. The busiest teams, as a bounded top N with an `other` bucket. The Space-Saving algorithm keeps
    that list bounded. Nothing on this path holds the team ID, so a team here is the pseudonym the
    mirror sends.
30. The number of distinct teams, as one gauge, estimated with HyperLogLog.
31. No metric carries a URL. No metric carries an unbounded team label. The team ID space is in the
    low millions, so a `team_id` label on a per-request metric is unbounded. The time series database and the pod that exports the metric
    both pay that cost.

### Security: what we never connect to

These rules exist to stop server-side request forgery. The URLs come from a page the lane did not
write, so an attacker chooses them, and the request leaves from inside our network.

32. The lane must never connect to an IP address that is not globally routable. That covers
    loopback, the RFC 1918 private ranges, link-local, carrier-grade NAT, multicast, and the
    reserved ranges, in IPv4 and IPv6. Smokescreen, the egress proxy, enforces this in production.
    `httpStaticLookup`, our DNS hook for undici, enforces it when no proxy is set.
33. The check must use the same DNS answer as the connection. DNS rebinding defeats any other
    order. An attacker who owns a name can return a different IP address on every lookup. Code that
    resolves a name, checks the IP address, then passes the name to a second resolver checks one
    address and connects to another.
34. The collector is the URL policy the mirror runs before it publishes. It drops a URL that a later
    check refuses, so that URL never reaches the topic. It drops:
    - a host that is not public
    - a scheme that is not HTTPS
    - a port that the scheme does not own
    - a URL that is too long
    - a URL that carries a signature the lane recognizes
35. Every check in rule 34 runs again in the lane, on the first URL and on every redirect target.
    The network layer performs none of them. Smokescreen limits which IP addresses we reach, not
    which service we reach at those addresses.

Neither implementation passes a name onward, which is what satisfies rule 33. Smokescreen resolves
the name, checks the IP addresses it got, and connects to one of those. `httpStaticLookup` resolves
the name, checks the IP addresses it got, and hands that list to undici, which connects to them.

The lane repeats the collector's checks because nothing below the lane performs them. Smokescreen
sees an IP address, not a scheme, a port, or a hostname, so the collector and the lane are the only
two places these run, and the two must agree. Both allow HTTPS on port 443 and nothing else.

The signature check is best effort by design. A signature says the operator serves that URL to a
holder of the signature rather than to anyone who asks, so principle two sends an ambiguous case the
way of not fetching. It also expires, so a URL that waits in a delay topic arrives dead and records
a 403 as a permanent answer.

The lane names the schemes it recognizes rather than trying to detect a signature in general. It
reads `X-Amz-Signature`, `X-Amz-Credential`, `X-Amz-SignedHeaders` and `Signature` on any host, `s`
on an imgix host, and a Cloudinary `/s--<token>--/` path segment. A name is host-scoped when it means
something else elsewhere: `s` sizes a Gravatar avatar. An unrecognised scheme still reaches the
fetcher, so a signed fetch has to fail safely rather than be impossible.

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

### robots.txt

36. The lane reads robots.txt for the origin of a URL. An origin is a scheme, a host, and a port
    together. One registrable domain holds many origins, so one answer does not cover every origin.
37. The lane caches a robots.txt answer for 24 hours. RFC 9309 sets that ceiling. A site that adds a
    rule today then blocks the lane tomorrow, rather than in a month.
38. The lane follows up to five consecutive redirects when it requests robots.txt, and it follows a
    redirect that leaves the authority. RFC 9309 requires both. Rule 7 forbids the same move for an
    image, so this rule is the exception to it. The rules the lane reads at the end of the chain
    govern the origin the lane asked about. For the avoidance of doubt, a redirect to another host
    does not make the answer apply to that host. A chain longer than five redirects reads as
    unreachable, and rule 43 then applies. RFC 9309 permits the looser reading that the origin
    serves no file, so this rule is stricter than the standard.
39. The lane parses the first 500 KiB of robots.txt and ignores the bytes after that. RFC 9309 sets
    500 KiB as the smallest limit a crawler may use.
40. A 404 or a 410 means the origin serves no robots.txt. The lane may fetch every URL on that
    origin.
41. Any other 4xx means the origin refused the request. The lane reads that refusal as a disallow for
    the whole origin. It covers 401, 403, and 451. RFC 9309 groups these codes with the codes that
    allow, so this rule is stricter than the standard. An origin that refuses robots.txt usually
    refuses the images too. The lane then records each image as forbidden.
42. A 429 is neither a refusal nor an answer. The origin asks for fewer requests. The lane reads a
    429 as unreachable. Google makes the same exception.
43. A 5xx, a timeout, or a connection error means the origin is unreachable. The lane must then treat
    every URL on that origin as disallowed. The lane holds the origin for one hour. Each further
    failure doubles the hold. The lane records no URL it holds this way, so the mirror offers each one again.
44. A cached answer may stay in use past its 24 hours while the origin is unreachable. RFC 9309
    allows this. If the lane holds an answer for that origin, the hold uses that answer.
45. A URL that robots.txt disallows is an answer. The lane writes it to the crawl history, as it
    writes a 404. The lane does not request that URL again while the entry lives.
46. The lane matches its own product token and the `*` group. It also counts every URL that a common
    AI training token disallows. It fetches those URLs and only counts them, so phase 0 measures the cost of
    the stricter rule.

### Identity

47. Every request carries the same user agent. It names one product token and one URL. That URL tells
    an operator what the lane does and how to refuse it.
48. The user agent never names a browser. An operator who sees a browser name from a crawler reads it
    as evasion rather than as an unverified bot. Cloudflare removes an operator from its verified list
    for evasion. A removal is harder to reverse than a first application.
49. Every request carries a Web Bot Auth signature. An operator can then verify that the request came
    from the lane. The operator does not need to trust the user agent. The signature uses three headers, per RFC 9421:
    `Signature`, `Signature-Input`, and `Signature-Agent`.
50. `Signature-Agent` names the origin that serves the lane's public key. That origin serves the key
    at `/.well-known/http-message-signatures-directory`.
51. Cloudflare refuses some signature components and parameters. The signature omits them: the
    `@query-params` and `@status` components, and the `sf`, `bs`, `key`, `req`, and `name` parameters.
    Every value is ASCII.
52. The `expires` parameter leaves the request enough time to reach the verifier.
53. The private key reaches the pod from the secret store. It appears in no log, no metric, and no
    error message.
54. The lane publishes no list of egress IP addresses. The lane shares its egress with every other
    proxied workload. An operator who blocks those addresses to refuse the lane also blocks the
    webhook delivery that operator asked for.

### Opt-out signals

`robots.txt` speaks about a path. It cannot express a rule for one image, because an image is a
binary with its own URL. These signals can. Each one arrives on a response the lane already reads,
or in a file the lane already fetches, so none of them costs an extra request.

55. The lane reads a response signal on every response it would otherwise act on. That means a 2xx
    it would read, and a 3xx it would follow. It does not read one on a 4xx or a 5xx, because it
    already refuses those, and an opt-out label there would misreport the reason.
56. Each of these signals refuses the URL on its own:

    | Signal            | Where it arrives                                | It refuses when                  |
    | ----------------- | ----------------------------------------------- | -------------------------------- |
    | `X-Robots-Tag`    | Response header                                 | It carries `noai` or `noimageai` |
    | `Content-Usage`   | Response header, and a rule in robots.txt       | Its dictionary sets `train-ai=n` |
    | `Content-Signal`  | A rule in robots.txt                            | It sets `ai-train=no`            |
    | `tdm-reservation` | Response header, and `/.well-known/tdmrep.json` | It is `1`                        |

57. A signal that is absent means unknown. It does not mean permission. The lane never reads silence
    as consent.
58. The most restrictive signal wins. One refusal anywhere in the chain stops the fetch, whatever the
    other signals say.
59. A refusal is an answer. The lane writes the URL to the crawl history under rule 24, and counts
    which signal refused it.
60. The lane counts `X-Robots-Tag: noindex` and does not act on it. `noindex` speaks about search
    rather than about training. Phase 0 measures what obedience would cost before we choose it.
61. `Content-Signal` uses the label `ai-train`. The AIPREF draft uses `train-ai` for the same idea.
    The lane reads both spellings, because they belong to two different specifications.

TDMRep gives a rightsholder three ways to reserve their rights over text and data mining. The lane
reads two of them. Article 4 of the EU DSM Directive grants a permission unless the rightsholder
reserves those rights by machine-readable means, so a reservation removes a permission rather than
adds a prohibition.

62. The lane reads `/.well-known/tdmrep.json` for the origin of a URL. That file follows the same
    path as robots.txt. Both answer for one origin, so both use one fetch, one cache of 24 hours,
    and the hold of rule 43.
63. A rule in that file refuses the URL when its location covers the URL and it sets
    `tdm-reservation` to 1.
64. TDMRep lets the response header supersede the file. The lane does not rank them. A refusal in
    either one refuses the URL, under rule 58. The lane is therefore stricter than the
    specification when the file reserves and the header releases, and principle two is the reason.
65. The lane does not read the HTML `meta` form of the reservation. The lane fetches images and
    parses no HTML.
66. The lane reads every signal that answers for a whole origin before it requests an image from
    that origin. Those are robots.txt and tdmrep.json. A refusal there costs the host nothing and
    covers every URL on it. A refusal in a response header costs the host one fetch, and covers one
    URL.

### Politeness a site asks for

67. `Crawl-delay` in robots.txt sets a minimum interval between two requests to a domain. The lane
    obeys it.
68. The lane uses the longer of its own interval and the one `Crawl-delay` names. It never uses the
    shorter one.
69. One registrable domain can hold several origins, and each origin can name a different
    `Crawl-delay`. The lane uses the longest value it holds for that domain.
70. A `Crawl-delay` longer than the pass deadline sends the URL to a delay topic. The pass does not
    wait it out, because a pass holds every other domain in the batch.
71. The lane holds at most one connection to one resolved IP address at a time. Many domains can
    share one server, and the domain limit of rule 2 does not see that.
72. Rule 71 counts inside one pod. A pod owns whole partitions, so it sees only the domains those
    partitions carry. Nothing counts across pods, as rule 19 says of the rest of this knowledge.

### Conditional requests

A crawl history entry lives 30 days, and then the lane wants the image again. Most images do not
change in 30 days. A conditional request asks the server to send the image only when it changed.

73. The lane stores the `ETag` a server sends with an image, and stores the `Last-Modified` value as
    well. Both live beside the crawl history entry for that URL, so the entry holds more than a
    timestamp.
74. The lane sends `If-None-Match` with the stored `ETag` when it fetches that URL again.
75. The lane sends `If-Modified-Since` with the stored `Last-Modified` only when it holds no `ETag`.
    An `ETag` carries no date, so it avoids the date format problems a `Last-Modified` value has.
76. A `304` answer means the image did not change. The server sends no body, so the answer costs a
    few hundred bytes rather than the whole image.
77. A response can name a freshness lifetime, and `immutable` names one that does not change. The
    lane sends no request for that URL while that lifetime lasts.
78. A `304` answer means the lane never reads the bytes. A change to the scrub lane or to the model
    therefore needs a way to fetch every image again, and the lane provides one.

### One fetch for every customer

A CDN logo appears in the recordings of many customers. The lane once fetched it one time for each
of them, because the crawl history key held the team. The request count then grew with the customer
count rather than with the number of distinct images.

79. The lane fetches a URL one time, however many customers refer to it. The crawl history key holds
    no team.

### The request the lane sends

80. The lane requests the URL that the record holds. It does not change the path, the query, or the
    case of any part. The collector canonicalizes a URL one time, and a second change here could
    request a resource the page never requested.
81. The lane accepts a compressed response. It names the encodings it can read in `Accept-Encoding`,
    and it never refuses a response because the server compressed it. The site pays for the
    bandwidth, so the site decides how many bytes it sends.

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

## The specifications these rules follow

| Specification                                                                                                            | What it governs here                                                                                                                          |
| ------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html), Robots Exclusion Protocol                                       | Rules 36 to 46. The response classes, the 24 hour cache, the redirect count, the 500 KiB parse limit, and how a product token matches a group |
| [TDMRep](https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240202/), W3C Community Group Final Report        | Rules 56 and 61 to 64. A Community Group report, which is not a W3C Standard                                                                  |
| [Directive (EU) 2019/790](https://eur-lex.europa.eu/eli/dir/2019/790/oj), Article 4                                      | Why a TDMRep reservation matters. It removes a permission rather than adds a prohibition                                                      |
| [RFC 9421](https://www.rfc-editor.org/rfc/rfc9421.html), HTTP Message Signatures                                         | Rules 47 to 50. The signature, and the components and parameters it covers                                                                    |
| [draft-meunier-webbotauth-httpsig-protocol](https://datatracker.ietf.org/doc/draft-meunier-webbotauth-httpsig-protocol/) | Rules 47 and 48. Web Bot Auth. An individual submission, not yet adopted by the working group                                                 |
| [RFC 7517](https://www.rfc-editor.org/rfc/rfc7517.html), JSON Web Key                                                    | Rule 50. The key directory, and the rule that a reader ignores a member it does not understand                                                |
| [RFC 7638](https://www.rfc-editor.org/rfc/rfc7638.html), JWK Thumbprint                                                  | Rule 50. The `kid`, computed over the required members only                                                                                   |
| [RFC 9651](https://www.rfc-editor.org/rfc/rfc9651.html), Structured Field Values                                         | Rule 57. The `Content-Usage` dictionary                                                                                                       |
| [draft-ietf-aipref-attach](https://datatracker.ietf.org/doc/draft-ietf-aipref-attach/)                                   | Rule 57. `Content-Usage`. A working group draft, and it expired in 2026                                                                       |
| [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html), HTTP Semantics                                                  | Rule 17, `Retry-After`. Also how a reader joins repeated field lines                                                                          |
| [RFC 1918](https://www.rfc-editor.org/rfc/rfc1918.html)                                                                  | Rule 32. One of the ranges that is not globally routable                                                                                      |
| [Public Suffix List](https://publicsuffix.org/)                                                                          | The registrable domain, which is the key of the frontier and of the host budget                                                               |

`noai` and `noimageai` in rule 56 have no specification. They are a convention that art hosting
platforms adopted, and `X-Robots-Tag` is the transport.

Two of these are unstable. The Web Bot Auth draft is an individual submission, so its header names
can change. The AIPREF draft that defines `Content-Usage` expired, and its vocabulary lost three of
its five categories between revisions.
