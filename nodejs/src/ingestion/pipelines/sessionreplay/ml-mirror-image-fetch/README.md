# The image fetcher

This app downloads remotes images that are referenced by URLs in session recordings, and sends them onwards to the 
scrubber for PII removal / sanitization. These images are eventually used for AI Research.

It is a web crawler, but it does not follow links or discover new pages. It only fetches images and relevant config
files (e.g.`robots.txt`, `.well-known` files) and will follow redirects to do so.

This README is the specification for the crawler, any difference from this spec is a bug.

## Principles

- The image fetcher is open source, this README is publicly visible, and everything we are doing is in the open and fully transparent
- Any time there is ambiguity, we should resolve it in the direction of not fetching the image
- We only fetch images that are linked to by a Session Replay from a customer with AI training enabled, and respect known methods for websites to opt out of this fetching, regardless of whether there is a legal requirement to do so
- We have a high standard for politeness, and have aggressive rate limits to enforce this
- We combine many opt out signals, any one of them causes us to stop fetching. We pick the order that these are checked to prioritise legal requirements first, spec compliance second, and load on hosts third

## TL;DR

For PostHog accounts with AI training data enabled (note, you can check or modify an org's status in the [org settings](https://app.posthog.com/settings/organization-details)), we save a scrubbed copy of session recordings for use in [AI Research](https://posthog.com/blog/training-ai-models).

The [upstream Kafka consumer](/nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror) processes RRWeb events, and will scrub them and attach a ref to any image tags with external URLs. It posts those external URLs to our topic. We fetch those URLs and write the images to another topic, where the [image scrubber](/nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub) consumes them and writes them to S3, using the ref as a key. Then at data prep time, we can fetch the images for a given Session Recording by their key.

## Requirements


### 7. PII

**7.1** All image data must be sent to the image scrubber lane (via writing to it's Kafka topic) rather than written to S3 directly

**7.2** We must never fetch URLs that meet any of these criteria:
- an IP address host or localhost
- a host that is not public
- a scheme that is not HTTPS
- a non-empty port other than 443 or 80
- too long
- appears to be a pre-signed URL
- contains a non-empty userinfo section

We treat a URL as pre-signed if it contains certain parameters or path segments. Some apply to all domains, other to 
only specific domains. These checks are all case-insensitive.

Query parameters:

| Parameter             | Domain        | Notes |
|-----------------------|---------------|-------|
| `Signature`           |               |       |
| `Credential`          |               |       |
| `SignedHeaders`       |               |       |
| `X-Amz-Signature`     |               |       |
| `X-Amz-Credential`    |               |       |
| `X-Amz-SignedHeaders` |               |       |
| `s`                   | `*.imgix.com` |       |

Path segments:

| Parameter             | Domain        | Notes      |
|-----------------------|---------------|------------|
| `/s--<token>--/`      |               | Cloudinary |

**7.3** It's preferable if upstream systems run the subset of these checks that they are easily able to, to reduce load on the system

**7.4** All checks must be re-run if the URL is redirected



### 10. Opt-out signals

**10.1** Sites can refuse fetching by signalling this via these files:
* `/robots.txt`
* `/.well-known/tdmrep.json`

**10.2** These files apply their rules per origin, not registrable domain

**10.3** Sites can refuse fetching by signalling this via headers in the HTTP response

**10.4** Headers in an HTTP response apply their rules only to that URL

**10.5** Any one refusal from any source is enough to stop us fetching that URL

**10.6** This is the complete list of opt-out signals used by this lane:

| Signal            | Where it arrives                                | It refuses when                  |
|-------------------|-------------------------------------------------|----------------------------------|
| `X-Robots-Tag`    | Response header                                 | It carries `noai` or `noimageai` |
| `Content-Usage`   | Response header, and a rule in robots.txt       | Its dictionary sets `train-ai=n` |
| `Content-Signal`  | A rule in robots.txt                            | It sets `ai-train=no`            |
| `tdm-reservation` | Response header, and `/.well-known/tdmrep.json` | It is `1`                        |

**10.7** It does not happen in this lane, as we do not parse the bytes in fetched images, but the PLUS Data Mining property in
XMP can be `DMI-PROHIBITED-AIMLTRAINING`, `DMI-PROHIBITED-GENAIMLTRAINING`, and `DMI-PROHIBITED`, which is treated as an opt-out for that image.

**10.8** The refusal should be written to the crawl cache, to prevent attempting to fetch that URL in the future

**10.9** The lane ignores `X-Robots-Tag: noindex` as this is about indexing for search

**10.10** Opt-out signals are applied at fetch time. For the avoidance of doubt, if a signal changes in the future (e.g. a robots.txt change) we do not delete fetched images


### 11. robots.txt and tdmrep.json

**11.1** The lane must fetch the robots.txt and tdmprep.json for an origin before fetching any image URLS on that origin

**11.2** The robots.txt and tdmprep.json must be cached for 24 hours (the maximum allowed by RFC 9309)

**11.3** To avoid interruptions, we start requesting robots.txt and tdmprep.json again for an origin when the cached version is 23 hours old

**11.4** The lane follows up to 5 redirects when requesting robots.txt and tdmprep.json, including to a different authority. This happens without needing to push any messages to Kafka.

**11.5** A redirect chain longer than 5 counts as unreachable.

**11.6** A robots.txt or tdmprep.json fetched after following redirects applies to the original origin.

**11.7** The lane tries to parse every line of the robots.txt file, and ignores lines it cannot parse

**11.8** The lane must use an established robots.txt parsing library rather than creating its own

**11.9** If the response to fetching robots.txt is an HTML file instead of a text file (e.g. in the case of a misconfigured server), we still treat it as a text file and try to parse every line

**11.10** We parse the first 500KiB of robots.txt and discard the rest, as per RFC 9309 which sets this as a lower bound

**11.11** TODO does tdmrep have a maximum size

**11.12** A rule in that tdmrep.json refuses the URL when its location covers the URL and it sets `tdm-reservation` to 1.

**11.13** A 404 or a 410 while fetching robots.txt or tdmrep.json means the origin does not have that file

**11.14** No robots.txt or tdmrep.json means that no restrictions on fetching are applied by that file (there might be signals from other sources)

**11.15** Any other 4xx other than 404 or 410 means a refusal, and is treated as a disallow for the whole origin.

**11.16** A 429 is treated as unreachable (same behaviour as Google)

**11.17** A 5xx, a timeout, or a connection error means the origin is unreachable

**11.18** If the robots.txt or tdmrep.json for an origin was unreachable, we must use a previous cached version of the file, if it exists. Otherwise, we must treat this as a refusal, but only cache it for 1 hour instead of 24.


### 9. Web Bot Auth

**9.1** Our User Agent starts with `PostHogImageFetcherBot` and contains a link to https://posthog.com/docs/ai-research/image-fetcher-bot. An example value is `PostHogImageFetcherBot/1.0 (+https://posthog.com/docs/ai-research/image-fetcher-bot)`

**9.2** Every request carries a Web Bot Auth signature. An operator can then verify that the request
came from the lane. The operator does not need to trust the user agent. The signature uses three
headers, per RFC 9421: `Signature`, `Signature-Input`, and `Signature-Agent`.

**9.3** `Signature-Agent` names the origin that serves the lane's public key. That origin serves the
key at `https://us.posthog.com/.well-known/http-message-signatures-directory`, and answers with the media type
`application/http-message-signatures-directory+json`.

**9.4** Our implementation of Web Bot Auth is tested against Cloudflare's implementation specifically

**9.5** The lane does not publish a list of egress IP addresses.

**9.6** The page at https://posthog.com/docs/ai-research/image-fetcher-bot (from the User Agent) should link to this README hosted on github

**9.7** The signature covers `@authority` and `signature-agent`.

**9.8** `Signature-Input` carries `tag="web-bot-auth"`, a `keyid` holding the JWK thumbprint of the
signing key, `created`, and `expires`.

**9.9** `Signature-Agent` is a structured string inside double quotes. It is not a dictionary.


### 1. Limits

**1.1** Requests in flight never exceed the pod limit.

**1.2** Requests in flight to one registrable domain never exceed the domain limit.

**1.3** Requests to one registrable domain never exceed the rate its token bucket allows.

**1.4** A redirect is not a way around any limit. (e.g. if fetching a.com/image and a redirect to b.com/image is received, the first request counts towards a.com's limit and the second to b.com's)

**1.5** A wait is not a way around any limit (e.g. if a URL was waiting for the pod limit to free up, it must check the per-domain limit and all other limits before resuming)

**1.6** There is no global handling of concurrent request limits. As the kafka topic is partitioned by registrable domain, all concurrent request limited can be handled at the pod level.

**1.7** A Kafka partition rebalance should not cause us to temporarily go over pod-local limits

**1.8** In-flight concurrency limits apply to all external URL fetches (e.g. `robots.txt` files), not just images. It does not apply to internal services like DynamoDB or Kafka.

**1.9** Queued requests do not count towards in-flight limits, only active requests (i.,e. with a socket) do

**1.10** These are the limits in the system:

| Constant                                | Scope                                             | Value      |
|-----------------------------------------|---------------------------------------------------|------------|
| Requests in flight                      | pod                                               | 300        |
| Requests in flight per domain           | domain                                            | 6          |
| Requests per second per domain          | domain                                            | 1, burst 5 |
| Hop budget                              | one original URL, across every message it becomes | 10         |
| Redirects followed without republishing | one fetch                                         | 3          |
| Response bytes, compressed              | one response                                      | 2 MB       |
| Request timeout                         | one URL, redirects included                       | 10 seconds |
| Pass deadline                           | one pass                                          | 20 seconds |
| Pass wall time, worst case              | one pass                                          | 30 seconds |
| Domains tracked                         | pod                                               | 20000      |
| Crawl history entry                     | one URL                                           | 30 days    |

### 8. Smokescreen

**8.1** We must never fetch from an IP that is not globally routable (e.g. if a URL's DNS entrry points to a private IP)

**8.2** In production deployments, all fetches (of both images and other files like `robots.txt`) must go through Smokescreen

**8.3** Smokescreen must have private IP blocking enabled

**8.4** Smokescreen must allow reaching every domain

### 4. Back-off and retry delay

**4.1** One network failure for a domain applies to every URL queued for that domain in the same pass.

**4.2** One delay (e.g. from an HTTP 429 `Retry-After` or `Crawl-delay` header) applies to every URL queued for that domain in the same pass.

**4.3** Repeated network failures cause an exponential back-off per registrable domain

**4.4** Per-origin delays / back-off state is stored in memory on the pod

**4.5** We respect `Crawl-delay` in robots.txt, which sets a minimum interval between two requests to a domain.

**4.6** We use the `Crawl-delay` from the robots.txt from the same origin (not just registrable domain) as the URL.

**4.7** The lane uses the longer of its own interval and the `Crawl-delay`.

**4.8** A delayed retry must not block processing. A delayed retry goes to the back of the queue for its current batch, and if the delay durations has not passed by the time it reaches the front of the queue, it must instead republish to a delay Kafka topic.

**4.9** A `Crawl-delay` longer than the pass deadline immediately sends the URL to a delay topic

**4.10** A `Crawl-delay` longer than the longest delay topic is a refusal rather than a delay

**4.11** When republishing to a delay topic, URLs are published to the delay Kafka topic with the smallest delay that is greater than the required delay.


### 3. Hop budget

**3.1** Every retry or redirect costs one hop. This includes but is not limited to, network failures, rate limiting (e.g. HTTP 429), a redirect to the same or different registrable domain.

**3.2** Every URL starts with the default hop budget

**3.3** When URLs are republished back to Kafka, they must also store their current hop budget and the next time it is valid for them to be retried.

**3.4** Explicit refusals (such a denial by `robots.txt` or an HTTP 403/404) are not retried regardless of remaining hop budget.

**3.5** Retries cannot happen before the allowed time, but they may happen some time after. They should be published to the delay Kafka topic with the smallest delay that is greater than the required delay.

**3.6** Retries cannot delay for longer than the longest delay topic. A delay that is longer than the longest delay topic is treated as an explicit refusal.


### 2. Redirects

**2.1** When following a redirect to another registrable-domain, send the URL back to the frontier (e.g. so that per domain limits can be respected for the new domain)

**2.2** When following a redirect to the same registrable-domain, handle it within the same Kafka batch.

**2.3** After a redirect, all checks must be re-run on the new URL

**2.4** Redirects should keep their original key. This is necessary for the data prep phase to be able to find the image.

**2.5** A republished message carries the original ref. The ref is a hash of the original URL. A ref
built from a redirect target matches no recording.

### 5. Kafka mechanics

**5.1** There is no ordering requirement for fetching URLs. Keys or URLs have no ordering property

**5.2** Use at-least-once semantics, as duplicates are acceptable for this lane, the downstream image scrub lane, and S3 storage.

**5.3** The offset is committed only when it is durable (i.e. a positive result is written to the downstream kafka topic
and to the crawl history, or a negative result is written to crawl history)

**5.4** An un-parseable message is simply dropped, there is no DLQ

**5.5** A systematic error like not being able to reach Kafka or DynamoDB should throw. We should not drop messages in
that scenario.

### 6. Metrics

**6.1** These metrics are tracked for each completed URL
* Outcome
* Refusal reason if refused
* Time spent in the system
* Number of fetches
* Number of republishes


**6.2** These metrics are tracked for each completed fetch request (images and other files)
* Registrable domain (top N, bounded with Space-Saving algorithm)
* Root domain (top N, bounded with Space-Saving algorithm)
* Time taken
* HTTP response / network failure if any

**6.3** These metrics are tracked for each domain after establishing whether it is blocked or not
* Block status
* Block reason if any


### 12. Conditional requests

TODO this section needs something about Cache-Control and Expires headers

**12.1** The lane stores the `ETag` and `Last-Modified` in the crawl history for that URL

**12.2** An image may be fetched again if 30 days have passed since it was last fetched

**12.3** If there is a stored `ETag` The lane sends `If-None-Match` with the stored `ETag` when it fetches that URL again.

**12.4** If there is a stored `Last-Modified` but no `ETag`, the lane sends `If-Modified-Since` with the stored `Last-Modified`

**12.5** A `304` answer means the image did not change

**12.6** A response can name a freshness lifetime, and `immutable` names one that does not change.
The lane sends no request for that URL while that lifetime lasts.

### 13. URL key

**13.1** The lane fetches a URL one time, regardless of how many customers refer to it. The crawl history key
does not depend on the team.

**13.2** The URL used for the fetch is verbatim the same URL that was seen in a session replay.

**13.3** The key is based on a canonicalised version of the URL, so that similar URLs are folded into one.

### 14. HTTP request/response

**14.1** The lane accepts a compressed response. It specifies the encodings it can read in
`Accept-Encoding`.

**14.2** The lane never sends cookies, and ignores cookies that are set by the response

**14.3** The lane never sends a credential. That covers an `Authorization` header, a proxy credential,
 the userinfo of a URL, cookies, and known credential query parameters

**14.4** The lane never sends a `Referer`

**15.1** The lane refuses a response where `Content-Length` is over the byte limit

**15.2** The lane refuses a response where the total number of bytes sent is over the bytes limit, as soon as the byte limit is exceeded.

**15.3** The byte limits refers to bytes over the wire, which means it can refer to the compressed bytes.

**15.4** A compressed response should be submitted to the kafka topic still compressed, this lane never decompresses whole responses.

**15.5** This lane is not responsible for checking any limit on uncompressed size, that happens in the image scrubber

**15.6** The lane accepts these media types and refuses every other one:

| `Content-Type` | Format |
|----------------|--------|
| `image/png`    | PNG    |
| `image/jpeg`   | JPEG   |
| `image/gif`    | GIF    |
| `image/webp`   | WebP   |
| `image/bmp`    | BMP    |
| `image/avif`   | AVIF   |

**15.7** This lane does not check that the downloaded bytes match the expected media type. It is expected that the image scrubber will do this.

### 16. Crawl history store

**16.1** The crawl history store uses Dynamo DB

**16.2** It stores items with a TTL of 30 days

**16.3** It stores one item per URL

**16.4** It is eventually consistent, and so we do tolerate some duplicates.

**16.5** It does not immediately delete items after the TTL expires, so we must manually check it

**16.6** We should do reads and writes to the store in bulk, one bulk read at the start of handling a batch, and after doing all of the updates in memory while processing that batch, we should do one bulk write at the end to persist the changes and write new entries.

**16.7** An error communicating with the store is fatal and causes us to stop all processing

## 17. Delay topics

**17.1** As kafka has no concept of delay an individual message for a set amount of time, we instead delay messages by sending them to a delay queue

**17.2** There are 3 delay queues with 3 different delay times

```text
ai_research_session_replay_image_fetch_retry_1m
ai_research_session_replay_image_fetch_retry_10m
ai_research_session_replay_image_fetch_retry_1h
```

**17.3** The delay topic must read the publishing time of all URLs in the batch, and sleep until `max(publishing_times) + delay_period`


**17.4** A delay topic consumer needs to report itself healthy despite sleeping for long periods, e.g. using `KafkaConsumer.reportDeliberateWait()`

**17.5** A delay topic consumer may cause a URL to wait for longer than the delay period of that topic

**17.6** We do not alert on lag on a delay topic


## External specifications 

| Specification                                                                                                            | What it governs here                                                                                                                                                 |
|--------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html), Robots Exclusion Protocol                                       | Section 11. The response classes, the 24 hour cache, the redirect count, the 500 KiB parse limit, a line that does not parse, and how a product token matches a group |
| [TDMRep](https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240202/), W3C Community Group Final Report        | Requirement 10.6, and requirements 11.1 to 11.12. A Community Group report, which is not a W3C Standard                                                              |
| [IPTC Photo Metadata](https://www.iptc.org/std/photometadata/documentation/userguide/), Data Mining                      | Requirement 10.7. The PLUS Data Mining property, and the values that refuse AI training                                                                             |
| [Directive (EU) 2019/790](https://eur-lex.europa.eu/eli/dir/2019/790/oj), Article 4                                      | Why a TDMRep reservation matters. It removes a permission rather than adds a prohibition                                                                             |
| [RFC 9421](https://www.rfc-editor.org/rfc/rfc9421.html), HTTP Message Signatures                                         | Requirements 9.2 to 9.3 and 9.7 to 9.9. The signature, the components and parameters it covers, and the directory's own signature                                  |
| [Cloudflare Web Bot Auth](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/)               | Requirements 9.2, 9.4, and 9.7 to 9.9. What one verifier refuses, which is stricter than RFC 9421                                                                  |
| [draft-meunier-webbotauth-httpsig-protocol](https://datatracker.ietf.org/doc/draft-meunier-webbotauth-httpsig-protocol/) | Requirements 9.2 and 9.3. Web Bot Auth. An individual submission, not yet adopted by the working group                                                               |
| [RFC 7517](https://www.rfc-editor.org/rfc/rfc7517.html), JSON Web Key                                                    | Requirement 9.3. The key directory, and the rule that a reader ignores a member it does not understand                                                               |
| [RFC 7638](https://www.rfc-editor.org/rfc/rfc7638.html), JWK Thumbprint                                                  | Requirement 9.8. The `kid`, computed over the required members only                                                                                                  |
| [RFC 9651](https://www.rfc-editor.org/rfc/rfc9651.html), Structured Field Values                                         | Requirement 10.6. The `Content-Usage` dictionary                                                                                                                     |
| [draft-ietf-aipref-attach](https://datatracker.ietf.org/doc/draft-ietf-aipref-attach/)                                   | Requirement 10.6. `Content-Usage`. A working group draft, and it expired in 2026                                                                                     |
| [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html), HTTP Semantics                                                  | Requirement 4.2, `Retry-After`. Also how a reader joins repeated field lines                                                                                         |
| [RFC 1918](https://www.rfc-editor.org/rfc/rfc1918.html)                                                                  | Requirement 8.1. One of the ranges that is not globally routable                                                                                                     |
| [Public Suffix List](https://publicsuffix.org/)                                                                          | The registrable domain, which is the key of the frontier and of the host budget                                                                                      |

`noai` and `noimageai` in requirement 10.6 have no specification. They are a convention that art hosting
platforms adopted, and `X-Robots-Tag` is the transport.

Two of these are unstable. The Web Bot Auth draft is an individual submission, so its header names
can change. The AIPREF draft that defines `Content-Usage` expired, and its vocabulary lost three of
its five categories between revisions.
