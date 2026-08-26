# The image fetcher

This app downloads remote images that are referenced by URLs in session recordings, and sends them onwards to the
scrubber for PII removal / sanitization. These images are eventually used for AI Research.

It is a web crawler, but it does not follow links or discover new pages. It only fetches images and relevant config
files (e.g. `robots.txt`, `.well-known` files) and will follow redirects to do so.

This README is the specification for the crawler. Any difference from this specification is a bug.
The [implementation notes](./IMPLEMENTATION_NOTES.md) list known differences in the current code.

## Principles

- The image fetcher is open source. This README is publicly visible, and everything we are doing is in the open and fully transparent
- Any time there is ambiguity, we should resolve it in the direction of not fetching the image
- We only fetch images that are linked to by a Session Replay from a customer with AI training enabled, and respect known methods for websites to opt out of this fetching, regardless of whether there is a legal requirement to do so
- We have a high standard for politeness, and have aggressive rate limits to enforce this
- We combine many opt-out signals. Any one of them causes us to stop fetching. We check them in an order that prioritizes legal requirements first, specification compliance second, and load on hosts third

## TL;DR

For PostHog accounts with AI training data enabled (note, you can check or modify an org's status in the [org settings](https://app.posthog.com/settings/organization-details)), we save a scrubbed copy of session recordings for use in [AI Research](https://posthog.com/blog/training-ai-models).

The [upstream Kafka consumer](/nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror) processes RRWeb events, scrubs them, and attaches a global ref to image tags with external URLs. It posts those external URLs to our topic. We fetch those URLs and write the images to another topic, where the [image scrubber](/nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub) consumes them and writes them to S3, using the ref as a key. Then at data prep time, we can fetch the images for a given Session Recording by their key.

## Requirements

### 1. PII

**1.1** All image data must be sent to the image scrubber lane (via writing to its Kafka topic) rather than written to S3 directly

**1.2** We must never fetch URLs that meet any of these criteria:

- an IP address host or localhost
- a host that is not public
- a scheme that is not HTTPS
- a port other than the default port for the scheme. The lane only accepts HTTPS, so the only permitted port is 443
- too long
- contains a known URL credential, signature, token, or signed-header list
- contains a non-empty userinfo section

The presence of a listed signature, credential, token, or signed-header list is enough to refuse the URL. The lane does not validate the value or require other fields from the same signing scheme. Supporting fields such as the algorithm, creation time, and expiry do not cause a refusal by themselves.

The lane checks every occurrence of a query parameter, including an occurrence with an empty value. It decodes percent-encoding in each parameter name before a case-insensitive comparison. It refuses the URL if it cannot enumerate and decode every parameter. The lane compares path patterns case-insensitively. A `*` wildcard in a host pattern matches one non-empty DNS label.

Query parameters:

| Parameter              | Host pattern | Notes                                                                                                                                                                                                                                                                    |
| ---------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `__cld_token__`        |              | [Cloudinary](https://cloudinary.com/documentation/control_access_to_media) access token                                                                                                                                                                                  |
| `__token__`            |              | [Akamai](https://techdocs.akamai.com/adaptive-media-delivery/docs/generate-a-token-and-apply-it-to-content) token                                                                                                                                                        |
| `access_token`         |              |                                                                                                                                                                                                                                                                          |
| `api_key`              |              |                                                                                                                                                                                                                                                                          |
| `apikey`               |              |                                                                                                                                                                                                                                                                          |
| `auth_token`           |              |                                                                                                                                                                                                                                                                          |
| `authorization`        |              |                                                                                                                                                                                                                                                                          |
| `AWSAccessKeyId`       |              | AWS Signature Version 2 credential                                                                                                                                                                                                                                       |
| `Credential`           |              |                                                                                                                                                                                                                                                                          |
| `GoogleAccessId`       |              | [Google Cloud Storage](https://docs.cloud.google.com/storage/docs/access-control/signed-urls) Signature Version 2 credential                                                                                                                                             |
| `hdnea`                |              | [Akamai](https://techdocs.akamai.com/adaptive-media-delivery/docs/generate-a-token-and-apply-it-to-content) token                                                                                                                                                        |
| `hdntl`                |              | [Akamai](https://techdocs.akamai.com/adaptive-media-delivery/docs/generate-a-token-and-apply-it-to-content) token                                                                                                                                                        |
| `hdnts`                |              | [Akamai](https://techdocs.akamai.com/adaptive-media-delivery/docs/generate-a-token-and-apply-it-to-content) token                                                                                                                                                        |
| `id_token`             |              |                                                                                                                                                                                                                                                                          |
| `ik-s`                 |              | [ImageKit](https://imagekit.io/docs/media-delivery-basic-security) signature                                                                                                                                                                                             |
| `jsessionid`           |              | [Jakarta Servlet](https://jakarta.ee/specifications/servlet/6.1/jakarta-servlet-spec-6.1.html) session token                                                                                                                                                             |
| `OSSAccessKeyId`       |              | [Alibaba OSS](https://www.alibabacloud.com/help/en/oss/developer-reference/add-signatures-to-urls) credential                                                                                                                                                            |
| `phpsessid`            |              |                                                                                                                                                                                                                                                                          |
| `q-ak`                 |              | [Tencent COS](https://cloud.tencent.com/document/product/436/68284) credential                                                                                                                                                                                           |
| `q-signature`          |              | [Tencent COS](https://cloud.tencent.com/document/product/436/68284) signature                                                                                                                                                                                            |
| `s=<32-char token>`    |              | [Imgix](https://github.com/imgix/imgix-blueprint#securing-urls)                                                                                                                                                                                                          |
| `security-token`       |              | [Alibaba OSS](https://www.alibabacloud.com/help/en/oss/developer-reference/add-signatures-to-urls) temporary credential                                                                                                                                                  |
| `session_token`        |              |                                                                                                                                                                                                                                                                          |
| `sessionid`            |              |                                                                                                                                                                                                                                                                          |
| `sig`                  |              | Includes [Azure SAS](https://learn.microsoft.com/en-us/rest/api/storageservices/create-account-sas) and [Cloudflare Images](https://developers.cloudflare.com/images/optimization/hosted-images/serve-private-images/) signatures                                        |
| `Signature`            |              | Includes AWS, [CloudFront](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-creating-signed-url-custom-policy.html), and [Alibaba OSS](https://www.alibabacloud.com/help/en/oss/developer-reference/add-signatures-to-urls) signatures |
| `SignedHeaders`        |              | Signed URL header list                                                                                                                                                                                                                                                   |
| `token`                |              | Includes [Bunny](https://support.bunny.net/hc/en-us/articles/360016055099-How-to-sign-URLs-for-BunnyCDN-Token-Authentication) query tokens                                                                                                                               |
| `X-Amz-Credential`     |              | [AWS Signature Version 4](https://docs.aws.amazon.com/AmazonS3/latest/developerguide/sigv4-query-string-auth.html) credential                                                                                                                                            |
| `X-Amz-Security-Token` |              | [AWS Signature Version 4](https://docs.aws.amazon.com/AmazonS3/latest/developerguide/sigv4-query-string-auth.html) temporary credential                                                                                                                                  |
| `X-Amz-Signature`      |              | [AWS Signature Version 4](https://docs.aws.amazon.com/AmazonS3/latest/developerguide/sigv4-query-string-auth.html) signature                                                                                                                                             |
| `X-Amz-SignedHeaders`  |              | [AWS Signature Version 4](https://docs.aws.amazon.com/AmazonS3/latest/developerguide/sigv4-query-string-auth.html) signed header list                                                                                                                                    |
| `X-Cos-Security-Token` |              | [Tencent COS](https://cloud.tencent.com/document/product/436/68284) temporary credential                                                                                                                                                                                 |
| `X-Goog-Credential`    |              | [Google Cloud Storage](https://docs.cloud.google.com/storage/docs/access-control/signed-urls) Signature Version 4 credential                                                                                                                                             |
| `X-Goog-Signature`     |              | [Google Cloud Storage](https://docs.cloud.google.com/storage/docs/access-control/signed-urls) Signature Version 4 signature                                                                                                                                              |
| `X-Goog-SignedHeaders` |              | [Google Cloud Storage](https://docs.cloud.google.com/storage/docs/access-control/signed-urls) Signature Version 4 signed header list                                                                                                                                     |
| `x-oss-credential`     |              | [Alibaba OSS](https://www.alibabacloud.com/help/en/oss/developer-reference/add-signatures-to-urls) Signature Version 4 credential                                                                                                                                        |
| `x-oss-security-token` |              | [Alibaba OSS](https://www.alibabacloud.com/help/en/oss/developer-reference/add-signatures-to-urls) temporary credential                                                                                                                                                  |
| `x-oss-signature`      |              | [Alibaba OSS](https://www.alibabacloud.com/help/en/oss/developer-reference/add-signatures-to-urls) Signature Version 4 signature                                                                                                                                         |

Path patterns:

| Pattern                                       | Host pattern                      | Notes                                                                                                                                                                                                |
| --------------------------------------------- | --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/bcdn_token=<token>[&<field>=<value>...]/`   |                                   | [Bunny](https://support.bunny.net/hc/en-us/articles/360016055099-How-to-sign-URLs-for-BunnyCDN-Token-Authentication) token in the first path segment                                                 |
| `/p/<token>/n/`                               | `objectstorage.*.oraclecloud.com` | [Oracle pre-authenticated request](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/usingpreauthenticatedrequests_topic-To_create_a_preauthenticated_request_for_all_objects_in_a_bucket.htm) |
| `/s--<token>--/`                              |                                   | [Cloudinary](https://cloudinary.com/documentation/control_access_to_media) signature                                                                                                                 |
| `/storage/v1/object/sign/`                    |                                   | [Supabase](https://supabase.com/docs/guides/storage/cdn/smart-cdn) signed object                                                                                                                     |
| `/storage/v1/render/image/sign/`              |                                   | [Supabase](https://supabase.com/docs/guides/storage/cdn/smart-cdn) signed image                                                                                                                      |
| `;jsessionid=<token>` within any path segment |                                   | [Jakarta Servlet](https://jakarta.ee/specifications/servlet/6.1/jakarta-servlet-spec-6.1.html) session token                                                                                         |

**1.3** It's preferable if upstream systems run the subset of these checks that they are easily able to, to reduce load on the system

**1.4** All checks must be re-run if the URL is redirected

**1.5** The producer collects only the `src` attribute on `img`, `image`, and `picture` elements. Other source attributes are out of scope until this specification adds them.

### 2. Opt-out signals

**2.1** Sites can refuse fetching by signaling this via these files:

- `/robots.txt`
- `/.well-known/tdmrep.json`

**2.2** These files apply their rules per origin, not registrable domain

**2.3** Sites can refuse fetching by signaling this via headers in the HTTP response

**2.4** Headers in an HTTP response apply their rules only to that URL

**2.5** The lane first applies the precedence rules within each signal specification. After that step, one refusal from any source is enough to stop the lane from fetching that URL.

**2.6** This is the complete list of opt-out signals used by this lane:

| Signal            | Where it arrives                                | It refuses when                  |
| ----------------- | ----------------------------------------------- | -------------------------------- |
| `X-Robots-Tag`    | Response header                                 | It carries `noai` or `noimageai` |
| `Content-Usage`   | Response header, and a rule in robots.txt       | Its dictionary sets `train-ai=n` |
| `Content-Signal`  | A rule in robots.txt                            | It sets `ai-train=no`            |
| `tdm-reservation` | Response header, and `/.well-known/tdmrep.json` | It is `1`                        |

**2.7** It does not happen in this lane, as we do not parse the bytes in fetched images, but the PLUS Data Mining property in
XMP is an opt-out for that image when it has one of these values:

- `DMI-PROHIBITED`
- `DMI-PROHIBITED-AIMLTRAINING`
- `DMI-PROHIBITED-EXCEPTSEARCHENGINEINDEXING`
- `DMI-PROHIBITED-GENAIMLTRAINING`
- `DMI-PROHIBITED-SEECONSTRAINT`
- `DMI-PROHIBITED-SEEEMBEDDEDRIGHTSEXPR`
- `DMI-PROHIBITED-SEELINKEDRIGHTSEXPR`

**2.8** The lane ignores `X-Robots-Tag: noindex` as this is about indexing for search

**2.9** Opt-out signals are applied at fetch time. For the avoidance of doubt, if a signal changes in the future (e.g. a robots.txt change) we do not delete fetched images

**2.10** A `tdm-reservation` response header supersedes the matching value from `tdmrep.json`. The absence of the header does not reset the value from `tdmrep.json`.

### 3. robots.txt and tdmrep.json

**3.1** The lane must fetch the robots.txt and tdmrep.json for an origin before fetching any image URLs on that origin

**3.2** The lane caches robots.txt for 24 hours. RFC 9309 says that a crawler should not use a cached copy for more than 24 hours unless the file is unreachable.

**3.3** The lane caches tdmrep.json for 24 hours. TDMRep does not specify this duration. It is a PostHog policy.

**3.4** To avoid interruptions, the lane starts to refresh robots.txt and tdmrep.json when the cached version is 23 hours old. The lane can use the current cached version while one refresh is in progress.

**3.5** The lane follows up to 5 redirects when requesting robots.txt and tdmrep.json, including to a different authority in the same registrable domain. It follows these redirects without publishing to Kafka. The result still applies to the original origin. A redirect to another registrable domain makes the configuration file unreachable. This rule prevents a source partition from creating a second request budget for the redirect target. Configuration-file requests use the failure, cache, and retry rules in this section. They do not read or change image back-off or circuit-breaker state.

**3.6** A redirect chain longer than 5 counts as unreachable.

**3.7** A robots.txt or tdmrep.json fetched after following redirects applies to the original origin.

**3.8** The lane tries to parse every line of the robots.txt file, and ignores lines it cannot parse

**3.9** The lane uses [`@trybyte/robotstxt-parser`](https://github.com/trybyte-app/robotstxt-ts-port), a TypeScript port of Google's parser, for RFC 9309 group selection and path matching. The product token is `PostHogImageFetcherBot`. The lane uses the library's low-level parser to retain and process every field line for extensions such as `Crawl-delay`, `Content-Usage`, and `Content-Signal`.

**3.10** If the response to fetching robots.txt is an HTML file instead of a text file (e.g. in the case of a misconfigured server), we still treat it as a text file and try to parse every line

**3.11** We parse the first 500KiB of robots.txt and discard the rest. RFC 9309 requires a parser to support at least this size.

**3.12** TDMRep does not specify a maximum size for tdmrep.json. The lane refuses a tdmrep.json file larger than 500KiB. It treats this result as unreachable.

**3.13** The lane parses and applies tdmrep.json according to the [TDMRep Community Group Final Report](https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240510/). A matching reservation of `1` refuses the URL.

**3.14** A 404 or a 410 while fetching robots.txt or tdmrep.json means the origin does not have that file

**3.15** No robots.txt or tdmrep.json means that no restrictions on fetching are applied by that file (there might be signals from other sources)

**3.16** Any 4xx other than 404 or 410 means a refusal and is treated as a disallow for the whole origin. This is more conservative than Google, which treats 4xx responses other than 429 as if no robots.txt file exists.

**3.17** A 429 is treated as unreachable (same behavior as Google)

**3.18** A 5xx, a timeout, or a connection error means the origin is unreachable

**3.19** If the robots.txt or tdmrep.json for an origin is unreachable, the lane must use a previous cached version of the file if one exists. The lane tries to refresh it again after 1 hour. RFC 9309 permits using an older robots.txt file while the file is unreachable.

**3.20** If an unreachable configuration file has no previous cached version, the lane refuses the origin and caches that result for 1 hour. It must not write a 30-day terminal refusal for each URL in this case.

**3.21** The lane writes a terminal refusal to the URL crawl history. A transient configuration failure uses the 1-hour configuration-cache TTL from requirement 3.20 instead.

**3.22** The lane uses separate cache entries for robots.txt, tdmrep.json, and each URL crawl result. A robots.txt or tdmrep.json success, absence, or valid refusal has a 24-hour TTL. An unreachable result without a cached version has a 1-hour TTL. A terminal URL result has a minimum TTL of 30 days. If the response's explicit freshness lifetime is longer, the entry uses that longer TTL.

**3.23** A retained configuration body must be valid UTF-8. If the 500KiB robots.txt prefix ends inside a UTF-8 code point, the lane discards that incomplete code point. Any other invalid UTF-8 makes the configuration file unreachable.

### 4. Web Bot Auth

**4.1** Our User Agent starts with `PostHogImageFetcherBot` and contains a link to https://posthog.com/docs/ai-research/image-fetcher-bot. An example value is `PostHogImageFetcherBot/1.0 (+https://posthog.com/docs/ai-research/image-fetcher-bot)`

**4.2** Every request carries a Web Bot Auth signature. An operator can then verify that the request
came from the lane. The operator does not need to trust the user agent. The signature uses three
headers, per RFC 9421: `Signature`, `Signature-Input`, and `Signature-Agent`.

**4.3** `Signature-Agent` names the origin that serves the lane's public key. That origin serves the
key at `https://us.posthog.com/.well-known/http-message-signatures-directory`, and answers with the media type
`application/http-message-signatures-directory+json`.

**4.4** Our implementation of Web Bot Auth is tested against Cloudflare's implementation specifically

**4.5** The lane does not publish a list of egress IP addresses.

**4.6** The page at https://posthog.com/docs/ai-research/image-fetcher-bot (from the User Agent) should link to this README hosted on GitHub

**4.7** The request signature covers `@method`, `@authority`, `@target-uri`, and `signature-agent`.

**4.8** `Signature-Input` carries `tag="web-bot-auth"`, `alg="ed25519"`, a `keyid` holding the JWK thumbprint of the signing key, `created`, `expires`, and a random nonce. `expires` is 60 seconds after `created`.

**4.9** `Signature-Agent` is a structured string inside double quotes. Cloudflare requires this legacy form and rejects the dictionary form from the current Web Bot Auth draft.

**4.10** The first configured private key signs outbound requests. The key directory publishes every configured public key so that an operator can rotate keys.

**4.11** The key-directory response carries one signature for each published key. Each signature covers `@authority;req`, whose value is the constant `us.posthog.com`, and the response `Content-Digest`. It carries `alg="ed25519"`, `tag="http-message-signatures-directory"`, `keyid`, `created`, `expires`, and a random nonce. `expires` is 5 minutes after `created`. The response uses `Cache-Control: public, max-age=60`.

### 5. Limits

**5.1** Requests in flight never exceed the pod limit.

**5.2** Requests in flight to one registrable domain never exceed the registrable-domain limit during steady-state ownership. A bounded exception applies during the Kafka rebalance window described below.

**5.3** A positive configured request rate enables a token bucket for each registrable domain. The default zero value disables this rate limit and uses only the active-request limit. The same bounded rebalance exception applies when the token bucket is enabled.

**5.4** A redirect is not a way around any limit. Each image request counts against the registrable-domain budget of its target and the crawl delay of its target origin. The lane follows a configuration redirect only when its target has the same registrable domain. Each followed configuration request counts against that shared registrable-domain budget.

**5.5** A wait is not a way around any limit. A URL that waits for the pod limit must check the registrable-domain limit, the origin crawl delay, and all other limits before it resumes.

**5.6** There is no global handling of concurrent request limits. The Kafka topic is partitioned by registrable domain, using both the ICANN and private sections of the Public Suffix List. All origins under one registrable domain therefore go to one partition. One pod normally holds the shared registrable-domain request budget and the separate policy and crawl-delay state for each origin.

**5.7** On partition revocation, the consumer stops starting work for the revoked partitions and drains their active batch before it unassigns them. If the drain exceeds Kafka's rebalance timeout, Kafka can assign the partition to a new pod while the old pod finishes its active requests. During this exceptional window, one old owner and one new owner can each apply the registrable-domain limit and an enabled token bucket. The pod limit still applies independently to each pod. The lane does not use a distributed lease to close this window.

**5.8** In-flight concurrency limits apply to all external URL fetches (e.g. `robots.txt` files), not just images. It does not apply to internal services like DynamoDB or Kafka.

**5.9** Queued requests do not count towards in-flight limits. Only active requests, i.e. requests with a socket, count.

**5.10** These are the limits in the system:

| Constant                                   | Scope                                             | Value      |
| ------------------------------------------ | ------------------------------------------------- | ---------- |
| Requests in flight                         | pod                                               | 300        |
| Requests in flight per registrable domain  | registrable domain                                | 6          |
| Requests per second per registrable domain | registrable domain                                | disabled   |
| Hop budget                                 | one original URL, across every message it becomes | 10         |
| Redirects followed without republishing    | one fetch                                         | 3          |
| Response bytes, compressed                 | one response                                      | 20 MiB     |
| Request timeout                            | one URL, redirects included                       | 10 seconds |
| Pass deadline                              | one pass                                          | 40 seconds |
| Pass wall time, worst case                 | one pass                                          | 50 seconds |
| Registrable domains tracked                | pod                                               | 20,000     |
| Origins tracked                            | pod                                               | 20,000     |
| Crawl history entry                        | one URL                                           | 30 days    |

**5.11** State is stored as follows:

| State                                                                    | Key                  | Location                                                     |
| ------------------------------------------------------------------------ | -------------------- | ------------------------------------------------------------ |
| Active requests, optional token bucket, back-off, and circuit breaker    | Registrable domain   | Memory on the pod that owns the Kafka partition              |
| Crawl delay and scheduled request count                                  | Origin               | Memory on the pod that owns the registrable-domain partition |
| Configuration request coalescing lock                                    | Origin and file type | Memory on the pod that owns the registrable-domain partition |
| robots.txt and tdmrep.json results                                       | Origin and file type | DynamoDB, with an optional hot cache in pod memory           |
| URL crawl history and HTTP cache metadata                                | Global canonical URL | DynamoDB                                                     |
| Original ref, current URL, remaining image hops, and earliest retry time | One URL job          | Kafka record                                                 |

**5.12** A configured request rate, burst, active-request count, transient back-off, `Retry-After`, and circuit-breaker state use the registrable domain as their key. Configuration policy and `Crawl-delay` use the origin as their key. No request-control state uses the provider domain as its key.

**5.13** The pod limits both its registrable-domain runtime map and its origin runtime map to 20,000 entries because both key sets are unbounded.

**5.14** The pod can evict a registrable-domain entry only when all these conditions apply:

- The registrable domain has no active request or pending request grant.
- The registrable domain has no active back-off or breaker.
- The registrable domain's token bucket is disabled or full.

The pod can evict an origin entry only when all these conditions apply:

- The origin has no active or scheduled request.
- The origin has no reserved image-request start time.
- The origin's crawl delay has elapsed.

Removing an eligible entry cannot permit an earlier request.

**5.15** If either map is full and has no eligible entry, the pod does not make the request. It sends the job to the 1-minute delay topic. The record names `origin_map_full` or `registrable_domain_map_full` as the reason.

**5.16** Before scheduling a pass, the lane deduplicates jobs by global canonical URL ref. It keeps the most conservative hop, retry, and timing state for each ref.

**5.17** The pass queue groups jobs first by registrable domain and then by origin. It assigns capped proportional concurrency targets at both levels. It starts with each queue's share of the deduplicated pass and the available parent capacity. It caps the target at the queue's job count and the registrable-domain limit. It redistributes unused capacity until no eligible queue exceeds either cap.

**5.18** The queue selects the registrable domain that is furthest below its concurrency target. It uses the waiting job count and then insertion order as tie-breakers. It applies the same rule to origins within the selected registrable domain. The pod and registrable-domain limits still apply.

**5.19** The queue calculates remaining request capacity from active and waiting jobs. It applies the configured registrable-domain and pod limits. The defaults are 6 and 300. If fewer than 48 request slots remain, low-origin-diversity mode can start. More than 50 canonical URL jobs must still be eligible for a diversity deferral. The pass processes 8 more jobs for forward progress. It then republishes each eligible job in the waiting tail to the frontier without reducing the hop budget. Low-origin-diversity mode remains active for the rest of that pass.

This rule lets later Kafka records add domain and origin diversity when the current pass cannot use enough pod capacity. A job can receive this zero-wait diversity deferral once. A previously deferred job proceeds normally, subject to the pass deadline. This bound prevents a persistent dominant origin or one long run from creating a fast republish cycle without progress.

### 6. Smokescreen

**6.1** Smokescreen is the authoritative network boundary for outbound requests in production. It must refuse a connection to an IP address that is not globally routable.

**6.2** In production deployments, all fetches (of both images and other files like `robots.txt`) must go through Smokescreen

**6.3** Smokescreen must have private IP blocking enabled.

**6.4** Smokescreen must allow every hostname that resolves only to permitted public addresses.

**6.5** These controls prevent server-side request forgery. A page must not make the lane connect to an internal service, a loopback address, a link-local address, or a cloud metadata service. Smokescreen must check the resolved address for every connection so that DNS rebinding cannot bypass this control.

### 7. Back-off and retry delay

**7.1** This section applies to image requests. Configuration-file requests use the failure and retry rules in section 3 and do not change a registrable domain's image back-off or circuit-breaker state.

**7.2** A network error, timeout, HTTP 408, HTTP 425, HTTP 429, or HTTP 5xx response is a transient failure. It increments the registrable domain's consecutive transient-failure count. A successful response, valid redirect, or terminal HTTP response resets that count.

**7.3** One transient failure for a registrable domain applies to every image URL queued for that registrable domain in the same pass.

**7.4** The retry back-off after the first consecutive transient failure is 1 minute. Each further consecutive failure doubles the maximum delay, up to 1 hour. The actual delay is selected uniformly between one half and all of that maximum, inclusive.

**7.5** A valid `Retry-After` on HTTP 429 or HTTP 503 sets a minimum retry delay. The lane accepts either a non-negative integer number of seconds or an HTTP date. It uses the longer of `Retry-After` and the delay from requirement 7.4. It ignores an invalid or past value.

**7.6** After 5 consecutive transient failures, the registrable domain's circuit breaker opens for the calculated delay. When that period ends, one image request becomes the half-open probe. Other image requests for the registrable domain remain delayed until the probe completes.

**7.7** A successful, redirected, or terminal response to the half-open probe closes the circuit breaker and resets its failure count. A transient failure reopens it with the next exponential delay.

**7.8** Registrable-domain back-off, failure counts, and circuit-breaker state use the bounded pod memory described in requirement 5.11.

**7.9** The lane respects every `Crawl-delay` field line in the selected robots.txt group for `PostHogImageFetcherBot`. It accepts a non-negative decimal number of seconds, ignores invalid values, and uses the greatest valid value.

**7.10** `Crawl-delay` is the minimum interval between the start times of two image requests to the same origin. An origin without this field has no start-time interval. A positive configured request rate can also apply across the registrable domain. A request must satisfy every enabled limit.

**7.11** Back-off, `Retry-After`, and an open circuit breaker apply to every image URL queued for the registrable domain. `Crawl-delay` applies only to image URLs queued for the origin that published it. The lane uses the latest applicable not-before time.

**7.12** A delayed retry must not block processing. It goes to the back of the queue for its current batch. If the delay has not elapsed when it returns to the front, the lane republishes it to a delay Kafka topic.

**7.13** A delay longer than the pass deadline immediately sends the URL to a delay topic.

**7.14** A required delay longer than 1 hour is a terminal refusal rather than a sequence of passes through the 1-hour topic.

**7.15** When republishing to a delay topic, the lane uses the topic with the smallest delay that is greater than or equal to the required delay.

### 8. Hop budget

**8.1** Every HTTP retry or redirect for an image URL costs one hop. This includes network failures, rate limiting such as HTTP 429, and a redirect to the same or a different origin.

**8.2** Every URL starts with the default hop budget

**8.3** When URLs are republished back to Kafka, they must also store their current hop budget and the next time it is valid for them to be retried.

**8.4** Explicit refusals (such as a denial by `robots.txt` or an HTTP 403/404) are not retried regardless of remaining hop budget.

**8.5** Retries cannot happen before the allowed time, but they may happen some time after. They should be published to the delay Kafka topic with the smallest delay that is greater than or equal to the required delay.

**8.6** Retries cannot delay for longer than the longest delay topic. A delay that is longer than the longest delay topic is treated as an explicit refusal.

**8.7** The image hop budget does not apply to robots.txt or tdmrep.json. Each configuration-file request has its own budget of 5 redirects.

**8.8** A scheduling deferral before a network request does not cost a hop. This includes a deferral caused by the pass deadline or a full origin runtime map.

### 9. Redirects

**9.1** The lane treats HTTP 301, 302, 303, 307, and 308 as redirects. It resolves a relative `Location` against the current URL.

**9.2** When following a redirect to another origin, send the URL back to the frontier so that the new origin's limits can be applied.

**9.3** When following a redirect to the same origin, handle it within the same Kafka batch.

**9.4** After a redirect, all checks must be re-run on the new URL

**9.5** Redirects should keep their original key. This is necessary for the data prep phase to be able to find the image.

**9.6** A republished message carries the original ref. The ref is a hash of the original URL. A ref
built from a redirect target matches no recording.

**9.7** The lane follows no more than 3 same-origin redirects while it processes one frontier record. If the next redirect is also same-origin, the lane republishes its target to the frontier instead of recording a terminal failure.

**9.8** The republished target carries the original ref, remaining image-hop budget, and earliest retry time. Republishing resets the 3-redirect local count. It does not reset the total image-hop budget.

### 10. Kafka mechanics

**10.1** There is no ordering requirement for fetching URLs. Keys or URLs have no ordering property

**10.2** Use at-least-once semantics, as duplicates are acceptable for this lane, the downstream image scrub lane, and S3 storage.

**10.3** The consumer completes durable work in this order:

1. It publishes each image and every frontier or delay record to its destination Kafka topic and waits for the delivery acknowledgement.
2. It writes all required crawl-history changes to DynamoDB.
3. It returns from the batch so that the input fetch-topic offset can be stored.

A terminal refusal has no destination Kafka record, so it starts at step 2. A delayed retry has no terminal URL result in crawl history. These systems do not share a transaction. A failure before step 3 must throw. A replay can create a duplicate, which requirement 10.2 permits.

**10.4** A frontier or delay record is versioned JSON. Its Kafka key is the registrable domain of every job's current URL. One record can contain multiple jobs for that key. Each job has this schema:

```json
{
  "v": 2,
  "jobs": [
    {
      "originalRef": "imageurl:<hash>",
      "currentUrl": "https://images.example.com/image.png",
      "remainingHops": 10,
      "notBeforeMs": 0,
      "firstSeenAtMs": 1787241600000,
      "fetchCount": 0,
      "republishCount": 0,
      "lastRepublishReason": null
    }
  ]
}
```

`v` is the integer `2`. The parser also accepts the two version `1` shapes that preceded this schema, so records already in a topic drain across an upgrade. `jobs` contains 1 to 1,000 entries, and the decoded JSON record cannot exceed 512 KiB. `originalRef` is the ref calculated for the URL first seen in the replay. `currentUrl` is the next URL to request after any redirects. `remainingHops`, `notBeforeMs`, `firstSeenAtMs`, `fetchCount`, and `republishCount` are non-negative safe integers. `firstSeenAtMs` is the Unix time when the producer first collected the URL. `fetchCount` counts image HTTP requests, and `republishCount` counts frontier and delay-topic republishes. `lastRepublishReason` is `null`, `redirect`, `retry`, `not_ready`, `pass_deadline`, `origin_map_full`, or `registrable_domain_map_full`. The optional boolean `lowOriginDiversityDeferred` records that the job has already received its one zero-wait diversity deferral.

The parser ignores unknown fields so that a producer can add optional data without breaking an older consumer. It rejects a missing field, an invalid field type or value, an unsupported version, or a record whose jobs do not all match the Kafka key. It derives the current origin and registrable domain from `currentUrl` with the shared URL-policy implementation. It uses `originalRef` as the crawl-history key so that a redirect result completes the URL that the recording referenced.

**10.5** The fetcher drops an unparseable input message. The fetcher has no dead-letter topic.

**10.6** A systematic error like not being able to reach Kafka or DynamoDB should throw. We should not drop messages in
that scenario.

**10.7** A redirect, pass-deadline deferral, and low-origin-diversity deferral have no required wait. The lane publishes them to the frontier with `notBeforeMs` set to `0`. A retry, an early `notBeforeMs`, or a full runtime-state map uses the smallest delay topic that satisfies its required wait.

**10.8** Before Kafka delivery, the lane groups republished jobs by destination topic and the current URL's registrable domain. It packs each group into records of no more than 1,000 jobs and no more than 512 KiB. It sends records up to the configured pending-publish limit and waits for every started delivery acknowledgement. After one delivery fails, it starts no more records from that batch. It also stops starting deliveries 200 seconds after the poll batch began. This leaves time for in-flight delivery callbacks, the final crawl-history write, and offset handling before Kafka's 300-second poll limit. A record contains only one registrable domain and uses that registrable domain as its Kafka key.

A fetch batch can publish more frontier records than it consumed. This can occur when URLs from one source-domain record redirect to several target registrable domains. It can also occur when the added durable state makes a republished record reach a wire limit earlier than its input record. The lane must preserve those target-domain keys and wire limits. It must not send a zero-wait redirect to a delay topic only to keep the record count unchanged.

### 11. Metrics

**11.1** These metrics are tracked for each completed URL

- Outcome
- Refusal reason if refused
- Time spent in the system
- Number of fetches
- Number of republishes

**11.2** These metrics are tracked for each completed fetch request (images and other files)

- Time taken
- HTTP response class or network failure

**11.3** These metrics are tracked for each origin-policy or registrable-domain request-control decision

- Block status
- Block reason if any

**11.4** The registrable domain is the effective top-level domain plus one when the Public Suffix List's ICANN and private sections are both active. For example, it is `posthog.com` for `app.posthog.com` and `myapp.vercel.app` for `cdn.myapp.vercel.app`.

**11.5** The provider domain is the effective top-level domain plus one when only the ICANN section is active. For example, it is `posthog.com` for `app.posthog.com` and `vercel.app` for `myapp.vercel.app`. This document does not use the ambiguous term `root domain`.

**11.6** Every metric label defined by this lane uses a fixed set of values. HTTP responses use `2xx`, `3xx`, `4xx`, `5xx`, or `other`. Republish destination classes use `frontier` or `delay`. Republish topic classes use `frontier`, `retry_1m`, `retry_10m`, or `retry_1h`. Image scrub sources use `inline` or `url`. Unexpected scrub source formats use `other`. No label defined by this lane contains a configured Kafka topic name, registrable domain, provider domain, origin, host, URL, image ref, team, project, exception message, or other external value.

**11.7** The lane counts republished URLs by reason and bounded destination class. For each used topic class in a fetch batch, it observes the number of Kafka record delivery attempts, the number of attempted registrable-domain keys, and the wall time from topic-class scheduling until all started delivery attempts settle. It also observes total republish flush wall time and counts batches that reached the republish finalization deadline.

It counts transient retry causes as `timeout`, `error`, `rate_limited`, or `server_error`. It also counts republish failures, crawl-history keys affected by failed operations, and retry records by outcome.

**11.8** The lane observes completed poll batch duration, active batch age, distinct origins and registrable domains per poll batch, crawl-history operation duration, scheduler waits by `origin_crawl_delay`, `registrable_domain_rate`, or `request_capacity`, and URL age at ingestion. For deduplicated canonical URL jobs, it observes the URL share held by the top 1, 5, and 10 origins and registrable domains. It also observes the inverse Simpson effective count for both scopes. At fetch-pass start, it observes the request slots that the queue can use immediately and their ratio to the pod request limit. It counts passes that enter low-origin-diversity mode and observes the origins, canonical URL jobs, and request slots that remain at entry. The pass-budget saturation ratio is `pass_deadline` republishes divided by completed URLs plus all republishes.

**11.9** Alerts use frontier-topic lag, pass-budget saturation, active batch age, delivery failures, and invalid frontier or retry input. Durable log alerts cover one-shot failures that can stop a pod before Prometheus scrapes its counters. Requirement 16.6 still prohibits alerts on delay-topic lag.

### 12. Conditional requests

**12.1** The lane stores the request time, response time, `ETag`, `Last-Modified`, `Date`, `Age`, `Cache-Control`, and `Expires` metadata in the crawl history for that URL.

**12.2** The default minimum interval between two fetches of one image URL is 30 days.

**12.3** If there is a stored `ETag`, the lane sends `If-None-Match` with the stored `ETag` when it fetches that URL again.

**12.4** If there is a stored `Last-Modified` but no `ETag`, the lane sends `If-Modified-Since` with the stored `Last-Modified`

**12.5** A `304` response means the image did not change. The lane keeps the existing image and merges the response metadata from the `304` response into the stored metadata as RFC 9111 requires.

**12.6** The lane calculates the explicit freshness lifetime as a shared cache under RFC 9111. It uses `s-maxage`, then `max-age`, then `Expires` minus `Date`. The stored response time substitutes for a missing `Date`. It calculates current age as `max(0, response_time - Date, Age + response_time - request_time) + max(0, now - response_time)`. It treats a missing or invalid `Age` as 0, subtracts current age from the freshness lifetime, and treats a negative result as 0. Another missing or invalid value contributes no freshness time.

**12.7** The next permitted fetch time is the later of 30 days after the response arrived and the end of its explicit freshness lifetime.

**12.8** `no-cache`, `no-store`, `private`, and `must-revalidate` do not extend the next permitted fetch time beyond the default 30 days. The lane can keep the minimum crawl-history data that it needs for deduplication. It does not treat these cache directives as opt-out signals.

**12.9** `immutable` does not create or extend a freshness lifetime. It means that the lane must not send a conditional request while the stored response is fresh. The lane revalidates a stale response in the same way as a response without `immutable`.

### 13. URL key

**13.1** The lane fetches a URL one time within its crawl-history interval, regardless of how many customers refer to it. The ref and the crawl-history key do not depend on the team.

**13.2** The URL used for the fetch is the same URL that was seen in a session replay. The lane does not remove or reorder path or query data. A URL that contains userinfo is refused under requirement 1.2. A URL fragment is not part of an HTTP request target and is not sent to the server.

**13.3** The key uses the shared Rust URL-policy implementation to canonicalize the URL. The canonical form uses the parser's serialized HTTPS URL, lowercases and IDNA-encodes the host, removes a trailing DNS root dot, removes the fragment, omits the explicit default port `443`, and uses `/` for an empty path. It does not sort path segments or query fields. The shared parser's serialization is authoritative for percent-encoding and dot-segment normalization.

The fetch URL keeps the original query verbatim. The global ref uses a canonical query that removes every occurrence of a volatile query field after percent-decoding its name and comparing it case-insensitively. The implementation filters raw query fields and never rebuilds a query. Every retained field stays byte-for-byte unchanged. The global volatile field names are `cb`, `nocache`, and `rnd`. If the URL contains `_nc_ohc`, the scoped volatile field names are `_nc_ohc`, `_nc_ht`, `ccb`, `oe`, `oh`, and `stp`. These lists are part of the shared URL policy. A new volatile field requires a specification change and shared test vectors. A credential field is refused under requirement 1.2 before canonicalization and is never removed to make a URL acceptable. If several fetch URLs in one collection batch map to one global ref, the first collected fetch URL becomes the fetch candidate.

**13.4** A URL ref does not contain a team identifier, a team pseudonym, or a key derived from one team. The same canonical URL produces the same ref for every team.

**13.5** A URL ref has the form `imageurl:<hash>`. The producer calculates `GLOBAL_URL_KEY` with the existing `pseudonymize(ml_pseudonymization_secret, "image-url-key", "global-v1")` construction. The hash is the first 22 base64url characters of `HMAC-SHA256(GLOBAL_URL_KEY, canonical_url)`. Every producer must use this construction. The DynamoDB crawl-history key for the original URL is the same `imageurl:<hash>` string.

**13.6** The mirror stores the ref in a sibling attribute named `data-anon-image-ref-<attribute>`. For example, the ref for `src` is stored in `data-anon-image-ref-src`. The source attribute keeps its image placeholder.

**13.7** Data preparation uses the suffix of the ref attribute to find the source attribute. If the ref resolves, data preparation replaces the placeholder with the scrubbed image.

**13.8** Data preparation removes the ref attribute whether or not the ref resolves. The ref is a hash that has no meaning in training data and would appear as random noise.

### 14. HTTP request/response

**14.1** The lane accepts up to 4 `identity`, `gzip`, `deflate`, `br`, and `zstd` content codings and refuses every other coding. It sends `gzip, deflate, br, zstd` in `Accept-Encoding`; `identity` remains acceptable as HTTP defines.

**14.2** The lane never sends cookies, and ignores cookies that are set by the response

**14.3** The lane never sends a credential. That covers an `Authorization` header, a proxy credential,
the userinfo of a URL, cookies, and known credential query parameters

**14.4** The lane never sends a `Referer`

**14.5** The lane refuses a response where `Content-Length` is over the byte limit

**14.6** The lane refuses a response as soon as the total number of bytes sent exceeds the byte limit.

**14.7** The byte limit applies to bytes over the wire, including compressed bytes.

**14.8** The lane should submit a compressed response to the Kafka topic without decompressing it. The lane never decompresses whole responses.

**14.9** The image scrubber decodes the response with a streaming size check and refuses it as soon as the uncompressed bytes exceed 20 MiB. It must not allocate or decode an unbounded output before it applies this check.

**14.10** The lane accepts these media types and refuses every other one:

| `Content-Type` | Format |
| -------------- | ------ |
| `image/png`    | PNG    |
| `image/jpeg`   | JPEG   |
| `image/gif`    | GIF    |
| `image/webp`   | WebP   |
| `image/avif`   | AVIF   |

**14.11** This lane does not check that the downloaded bytes match the expected media type. It is expected that the image scrubber will do this.

**14.12** A `200` response is the only successful response that carries a new image body. Other 2xx responses are terminal failures for that URL.

**14.13** The redirect responses in section 9 require a valid `Location` value. A missing or invalid value is a terminal failure for that URL.

**14.14** The lane handles `304` as specified in section 12.

**14.15** HTTP 408, 425, 429, and 5xx responses are transient failures and use the retry rules in sections 7 and 8.

**14.16** Other 4xx responses and all remaining status codes are terminal failures for that URL.

**14.17** The HTTP helper preserves every response field line in received order, including repeated fields.

**14.18** The policy parser processes every repeated field line. It combines the lines in received order when the field permits a comma-separated value. A refusal in any repeated opt-out field refuses the URL.

### 15. Crawl history store

**15.1** The crawl history store uses DynamoDB

**15.2** A URL crawl-history item has a minimum TTL of 30 days. If requirement 12.7 gives a later permitted fetch time, the item must not expire before that time.

**15.3** It stores one crawl-history item per global canonical URL.

**15.4** It is eventually consistent, and so we do tolerate some duplicates.

**15.5** It does not immediately delete items after the TTL expires, so we must manually check it

**15.6** The lane uses one logical bulk-read phase at the start of a Kafka batch and one logical bulk-write phase at the end. The read includes the URL history items and the robots.txt and tdmrep.json cache items for every distinct origin in the batch. The lane keeps the updates in memory between these phases. A logical read uses as many `BatchGetItem` calls as necessary, with no more than 100 items in each call. A logical write uses as many `BatchWriteItem` calls as necessary, with no more than 25 items in each call. The lane uses bounded concurrency and retries unprocessed items with back-off.

**15.7** An error communicating with the store is fatal for the Kafka batch. The handler must throw so that the input offsets are not stored.

**15.8** The robots.txt and tdmrep.json caches use separate per-origin items. They do not share a TTL or an item with URL crawl history.

**15.9** The registrable-domain Kafka key puts all origins under that registrable domain on one pod, while each DynamoDB item belongs to one URL or one origin. Outside the bounded rebalance exception in requirement 5.7, one pod therefore builds updates for a given item. Before each `BatchWriteItem` call, the lane folds repeated updates for one item into the last in-memory state so that a request never contains duplicate keys. A rebalance replay can write the same final state again, which requirement 15.4 permits. The lane does not use conditional writes or a distributed DynamoDB concurrency lock.

## 16. Delay topics

**16.1** Kafka cannot delay an individual message for a set amount of time. We delay messages by sending them to a delay queue

**16.2** There are 3 delay queues with 3 different delay times

```text
ai_research_session_replay_image_fetch_retry_1m
ai_research_session_replay_image_fetch_retry_10m
ai_research_session_replay_image_fetch_retry_1h
```

**16.3** All three delay topics set `message.timestamp.type=LogAppendTime`. The broker replaces each producer timestamp with the time when it appends the record. The delay-topic consumer uses these broker timestamps as the publishing times for all records in the batch. It waits one time, until `max(publishing_times) + delay_period`. It does not wait separately for each record.

**16.4** A delay topic consumer needs to report itself healthy despite sleeping for long periods, e.g. using `KafkaConsumer.reportDeliberateWait()`

**16.5** A delay topic consumer may cause a URL to wait for longer than the delay period of that topic

**16.6** We do not alert on lag on a delay topic

**16.7** A delay-topic batch can contain more than one record. A larger batch can make an older record wait longer, which requirement 16.5 permits.

**16.8** After the wait, the consumer publishes the full batch to the frontier and waits for all delivery acknowledgements before it stores the input offsets. A publish failure must throw so that the batch is read again.

**16.9** The delay consumer's `max.poll.interval.ms` must exceed the longest possible batch wait plus the time needed to publish the batch.

## 17. Fetcher to scrubber message format

**17.1** The fetcher publishes one Kafka record for each successful image fetch.

**17.2** The record key is the UTF-8 `imageurl:<hash>` ref from requirement 13.5.

**17.3** The record value is the response body as binary data. The value contains the bytes received after HTTP message framing is removed and before any `Content-Encoding` is decoded. It has no JSON envelope, base64 encoding, or other framing.

**17.4** The record has these Kafka headers:

| Header                 | Value                                                                                               |
| ---------------------- | --------------------------------------------------------------------------------------------------- |
| `content-type`         | The normalized media type accepted under requirement 14.10, in lowercase and without parameters     |
| `content-encoding`     | The response content codings in the order in which the server applied them, normalized to lowercase |
| `capture-timestamp-ms` | The Unix timestamp from the replay Kafka record where the collector first saw the URL               |

**17.5** The fetcher omits `content-encoding` when the response has no content coding or specifies `identity`. The scrubber treats a missing header as `identity`.

**17.6** The scrubber decodes up to 4 content codings in reverse order. It refuses an unsupported, malformed, or longer coding list. It must enforce its uncompressed input limit while it decodes the value.

**17.7** After content decoding, the scrubber checks that the bytes match `content-type` before it sends them to the image scrubber.

**17.8** Inline image records use an `image:<pseudo-team>:<hash>` key and raw image bytes. They carry `capture-timestamp-ms` from the source replay Kafka record.

**17.9** This design does not add a dead-letter topic. The existing image-scrubber dead-letter path and its replay preserve the original key, value, `content-type`, `content-encoding`, and `capture-timestamp-ms`. The dead-letter path can add diagnostic headers and update its replay counter.

**17.10** The maximum record size is the response byte limit in requirement 5.10 plus the maximum key, header, and Kafka protocol overhead. The fetcher producer, image-scrub topic, existing image-scrub dead-letter topic, and their consumers must accept that size.

**17.11** After scrubbing a URL-backed image, the image scrubber writes it to the deterministic S3 object key `<configured image prefix>/url/<hash>`, where `<hash>` comes from the `imageurl:<hash>` ref. URL-backed images do not use the time-partitioned shard index used by inline images.

**17.12** The image scrubber creates a URL object with `If-None-Match: *`. If an object already exists for the ref, the scrubber keeps it and treats the write as complete. The first completed S3 write is the version that data preparation reads. This policy makes the first fetch URL that reaches storage win when several fetch URLs map to one global ref.

**17.13** Data preparation converts each distinct ref to the deterministic object key and performs one direct S3 read. A missing object leaves the image placeholder in place and does not require a recrawl.

**17.14** Inline images keep their existing sharded S3 storage and Parquet index.

**17.15** After a successful S3 write, the scrubber observes capture-to-S3 duration in a fixed-bucket histogram. The `source` label is `inline` or `url`. The scrubber does not observe a URL candidate when the conditional write finds an existing object.

## External specifications

| Specification                                                                                                            | What it governs here                                                                                                                                                  |
| ------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html), Robots Exclusion Protocol                                       | Section 3. The response classes, the cache guidance, the redirect count, the 500 KiB parse limit, a line that does not parse, and how a product token matches a group |
| [TDMRep](https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240510/), W3C Community Group Final Report        | Requirements 2.6, 2.10, and section 3. A Community Group report, which is not a W3C Standard                                                                          |
| [IPTC Photo Metadata](https://www.iptc.org/std/photometadata/documentation/userguide/), Data Mining                      | Requirement 2.7. The PLUS Data Mining property, and the values that refuse AI training                                                                                |
| [Directive (EU) 2019/790](https://eur-lex.europa.eu/eli/dir/2019/790/oj), Article 4                                      | Why a TDMRep reservation matters. It removes a permission rather than adds a prohibition                                                                              |
| [Content Signals](https://contentsignals.org/)                                                                           | Requirement 2.6. The `Content-Signal` robots.txt rule and the `ai-train` category                                                                                     |
| [RFC 9421](https://www.rfc-editor.org/rfc/rfc9421.html), HTTP Message Signatures                                         | Requirements 4.2 to 4.3 and 4.7 to 4.11. The signatures, covered components, parameters, and the directory response                                                   |
| [Cloudflare Web Bot Auth](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/)               | Requirements 4.2, 4.4, and 4.7 to 4.11. Cloudflare's verification rules and legacy `Signature-Agent` format                                                           |
| [draft-meunier-webbotauth-httpsig-protocol](https://datatracker.ietf.org/doc/draft-meunier-webbotauth-httpsig-protocol/) | Requirements 4.2 to 4.3 and 4.7 to 4.11. Web Bot Auth. An active individual submission                                                                                |
| [RFC 7517](https://www.rfc-editor.org/rfc/rfc7517.html), JSON Web Key                                                    | Requirement 4.3. The key directory, and the rule that a reader ignores a member it does not understand                                                                |
| [RFC 7638](https://www.rfc-editor.org/rfc/rfc7638.html), JWK Thumbprint                                                  | Requirement 4.8. The `kid`, computed over the required members only                                                                                                   |
| [RFC 9651](https://www.rfc-editor.org/rfc/rfc9651.html), Structured Field Values                                         | Requirement 2.6. The `Content-Usage` dictionary                                                                                                                       |
| [draft-ietf-aipref-vocab](https://datatracker.ietf.org/doc/draft-ietf-aipref-vocab/)                                     | Requirement 2.6. The `train-ai` preference and how conflicting or invalid preferences are resolved                                                                    |
| [draft-ietf-aipref-attach](https://datatracker.ietf.org/doc/draft-ietf-aipref-attach/)                                   | Requirement 2.6. The `Content-Usage` response field and robots.txt rule                                                                                               |
| [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html), HTTP Semantics                                                  | Requirements 7.5 and 14.17. `Retry-After` and repeated field lines                                                                                                    |
| [RFC 9111](https://www.rfc-editor.org/rfc/rfc9111.html), HTTP Caching                                                    | Section 12. Freshness lifetime, current age, cache directives, and conditional revalidation                                                                           |
| [RFC 8246](https://www.rfc-editor.org/rfc/rfc8246.html), HTTP Immutable Responses                                        | Requirement 12.9. The effect of `immutable` during and after a response's freshness lifetime                                                                          |
| [DynamoDB BatchGetItem](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchGetItem.html)            | Requirement 15.6. Bulk reads, the 100-item request limit, and unprocessed keys                                                                                        |
| [DynamoDB BatchWriteItem](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchWriteItem.html)        | Requirement 15.6. Bulk writes, the 25-item request limit, and unprocessed items                                                                                       |
| [Google robots.txt behavior](https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec)                     | Requirements 3.16 and 3.17. The places where PostHog follows or is more conservative than Google                                                                      |
| [Smokescreen](https://github.com/stripe/smokescreen)                                                                     | Section 6. The outbound proxy that enforces the production network boundary                                                                                           |
| [Public Suffix List](https://publicsuffix.org/)                                                                          | The registrable and provider domains used for Kafka ownership and bounded metrics                                                                                     |

`noai` and `noimageai` in requirement 2.6 have no specification. They are a convention that art hosting
platforms adopted, and `X-Robots-Tag` is the transport.

Two of these are unstable. The Web Bot Auth draft is an individual submission, so its header names
can change. The AIPREF attachment and vocabulary documents are active working group drafts, so their
syntax and categories can also change.
