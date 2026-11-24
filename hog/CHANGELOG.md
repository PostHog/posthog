# hog

## 0.1.1 — 2026-11-24

### Patch changes

- [14edc1551ed](https://github.com/PostHog/posthog/commit/14edc1551ed747c985c93d457e60ce3b047fbf10) feat(replay-vision): accept a scanner scope on the API — Thanks @ksvat!
- [67f33c6bddf](https://github.com/PostHog/posthog/commit/67f33c6bddfb5e2e3d4a72c5b74476718e6a4308) feat(dashboards): read the first screen through cached_tiles on first load — Thanks @DanielVisca!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(error-tracking): add an issue tag rules api — Thanks @rafaeelaudibert!
- [73a58d58ac0](https://github.com/PostHog/posthog/commit/73a58d58ac08ae8dc1ce62872def8bb025b78941) feat(workflows): push message templates can be made transactional — Thanks @dmarchuk!
- [290eb90ca5f](https://github.com/PostHog/posthog/commit/290eb90ca5ffc6863752588dd77080a8e76b997f) feat(workflows): import suppressions and unsubscribe groups from sendgrid — Thanks @rafaeelaudibert!
- [d748b285e17](https://github.com/PostHog/posthog/commit/d748b285e1712dfb48dfb1373eca19a16c16bf53) feat(messaging): schedule a send up to 7 days ahead behind a flag — Thanks @Silthus!
- [c187112e560](https://github.com/PostHog/posthog/commit/c187112e560baf783406a753e94ab302ce96cce9) feat(notebooks): add notebook app builder — Thanks @mariusandra!
- [9cd7f1c1dca](https://github.com/PostHog/posthog/commit/9cd7f1c1dca2878808b3c0c7243b9b62fd68ef4f) feat(replay-vision): teach the agent tools a scanner scope — Thanks @ksvat!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(dashboards): add dashboards v2 scene — Thanks @rafaeelaudibert!
- [bcd9005b19c](https://github.com/PostHog/posthog/commit/bcd9005b19cec0e1129aef7f00bc769731df9153) fix(mcp): keep the next-page hint on exec text results — Thanks @richardsolomou!
- [47fe7f5c0bd](https://github.com/PostHog/posthog/commit/47fe7f5c0bdb913eea7627932e33c6e1aa8a00f4) fix(signals): write task commits only to the reports they target — Thanks @dmarticus!
- [35605f145e4](https://github.com/PostHog/posthog/commit/35605f145e4659da131124b89d5a40a77e05f814) chore(cli): give hog the typescript compiler api — Thanks @rafaeelaudibert!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(stamphog): skip owner review requests on fully attested pull requests — Thanks @rafaeelaudibert!
- [0f3d640e07a](https://github.com/PostHog/posthog/commit/0f3d640e07a443698a71a90548769cc2f5751faf) feat(mcp): add organization-create tool — Thanks @richardsolomou!
- [3304968b85d](https://github.com/PostHog/posthog/commit/3304968b85d808b52e3fd0f0bc73bde57ed4fb6f) feat(workflows): publish preview says when it moves steps onto the test sender — Thanks @Silthus!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) fix(cli): tell agents when the user can approve a hog ci setup request — Thanks @rafaeelaudibert!
- [e81248592fc](https://github.com/PostHog/posthog/commit/e81248592fca68bcc47d6ec6e4c3a9c0e61f88ff) feat(workflows): warn api callers when a workflow is live on the test sender — Thanks @Silthus!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(business-knowledge): give libraries their own tab and page — Thanks @rafaeelaudibert!
- [7a1d716eb4b](https://github.com/PostHog/posthog/commit/7a1d716eb4b80413ff884120aa3be262ac15798f) feat(auth): remove legacy team secret token paths — Thanks @patricio-posthog!
- [0b8256d2f15](https://github.com/PostHog/posthog/commit/0b8256d2f15635631c306d95d114f027add86a18) feat(marketing-analytics): mark recommendations applied when ads show the change — Thanks @jabahamondes!
- [d1458104235](https://github.com/PostHog/posthog/commit/d1458104235fc48384cbd43dc24d8a67c7283386) feat(aeo): filter ai visibility by a date range — Thanks @lricoy!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) fix(mcp): run a bare sql string sent to execute-sql as its query — Thanks @rafaeelaudibert!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(workflows): add MCP tools for workflow email sends and recipient activity — Thanks @rafaeelaudibert!
- [eb4e2f49f79](https://github.com/PostHog/posthog/commit/eb4e2f49f79082d1df7d9798e607ecacc86693cf) feat(workflows): let an email tool import ask for settings before it starts — Thanks @dmarchuk!
- [eb445ffb8da](https://github.com/PostHog/posthog/commit/eb445ffb8dad5cfb3a2832e0b7ac6b48241083b5) fix(mcp): keep expected errors out of error tracking — Thanks @richardsolomou!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) fix(cli): read only the xml entities in an info.plist — Thanks @rafaeelaudibert!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(cli): make hog auth status easy for a person to scan — Thanks @rafaeelaudibert!
- [50cb61e12dd](https://github.com/PostHog/posthog/commit/50cb61e12dd8f0bcb1eff482c4cef9539ecebe25) fix(signals): tell agents which inbox reports are free to take — Thanks @dmarticus!
- [6a68efef418](https://github.com/PostHog/posthog/commit/6a68efef418699392cb0eb9c2c6dffffae548cc0) `hog error-tracking upload` and `process` now build JavaScript and ProGuard symbol sets in hog-worker, and `--delete-after` cleans up there too. The uploads and the files are the same, and a large build takes far less time and memory. — Thanks @rafaeelaudibert!
- [a8cfbe60308](https://github.com/PostHog/posthog/commit/a8cfbe6030833ad5eef7afc1570159f65c9431e2) chore(aio): remove the `llma-tagger-test-hog` tool — Thanks @bernatixer!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(cli): show people a short hog overview and add hog whoami — Thanks @rafaeelaudibert!
- [b963f281b5e](https://github.com/PostHog/posthog/commit/b963f281b5e874c393d63df44537e8024e712a4a) fix(mcp): run exec search patterns through a linear-time regex engine — Thanks @richardsolomou!
- [d6b87f08c22](https://github.com/PostHog/posthog/commit/d6b87f08c22ca6cb9b1458c9931083fe983006e3) feat(workflows): import bounces, complaints, unsubscribes and lists from mailgun — Thanks @dmarchuk!
- [1e7bf475a8b](https://github.com/PostHog/posthog/commit/1e7bf475a8b8dae1002fa458dec7c5e9dff5acc6) Every install of hog now includes hog-worker, the program that reads and writes build output for `hog error-tracking`, and `hog upgrade` and the install scripts replace the two together. On Alpine and other musl systems, the install script now names the missing `libstdc++` and `libgcc` packages when hog can't start without them. — Thanks @rafaeelaudibert!
- [e9fe277f151](https://github.com/PostHog/posthog/commit/e9fe277f15168227d026939550707ab0ea53b301) feat(signals): list recently ended monitoring reports with their outcome — Thanks @rafaeelaudibert!
- [e9fe277f151](https://github.com/PostHog/posthog/commit/e9fe277f15168227d026939550707ab0ea53b301) chore(deps): update posthog-node to 6.0.4 in nodejs and services/mcp — Thanks @rafaeelaudibert!
- [5b91687e695](https://github.com/PostHog/posthog/commit/5b91687e6951f45a3b526880e5b35b6e88d1e6d9) feat(marketing-analytics): detect applied keyword gaps and brand negatives — Thanks @jabahamondes!
- [2b699330670](https://github.com/PostHog/posthog/commit/2b699330670e0603fb0e0a254bae61b68dcd172b) fix(alerts): write moved insight alert edits to the platform copy only — Thanks @jzhu13!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(metrics): find metric attributes by their values — Thanks @rafaeelaudibert!
- [91a8bcf9d9c](https://github.com/PostHog/posthog/commit/91a8bcf9d9cb9b2bdf972368547028f8e5d76442) feat(mcp): name more harnesses and drop structuredContent by default — Thanks @richardsolomou!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) fix(signals): expire spend receipts after three months — Thanks @rafaeelaudibert!
- [e8b71427be3](https://github.com/PostHog/posthog/commit/e8b71427be3366facd16890e8a6432fa58041bd2) `hog error-tracking upload` now reads ELF files, Mach-O files and dSYM bundles in hog-worker, with the same Rust code posthog-cli runs. — Thanks @rafaeelaudibert!
- [0dfaccad90a](https://github.com/PostHog/posthog/commit/0dfaccad90a1c9bd0c77f4011cf3dd1ac909e04d) chore(data-catalog): point agents at metric-list for catalog checks — Thanks @sinan-ku!
- [d236ac05fca](https://github.com/PostHog/posthog/commit/d236ac05fca131cd10973e830c9ccbcd958da4ef) feat(mcp): split writes from exec so clients can always allow reads — Thanks @richardsolomou!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) chore(aio): remove offline evaluations feature flag — Thanks @rafaeelaudibert!
- [e07a29787bc](https://github.com/PostHog/posthog/commit/e07a29787bc4371d86333051714e18b4b25f943d) `hog error-tracking clone` and Hermes uploads now read, write and package sourcemaps in hog-worker, with the same Rust code posthog-cli runs. — Thanks @rafaeelaudibert!
- [e9fe277f151](https://github.com/PostHog/posthog/commit/e9fe277f15168227d026939550707ab0ea53b301) fix(signals): let a person's agents work under their report claim — Thanks @rafaeelaudibert!
- [b3b03462622](https://github.com/PostHog/posthog/commit/b3b03462622931ef0e286c549844d5a82dee03ce) `hog error-tracking inject` now rewrites bundles and sourcemaps in hog-worker, a Rust program that ships next to hog. The files it writes are the same, and a large build takes far less time and memory. — Thanks @rafaeelaudibert!
- [b02d78db32d](https://github.com/PostHog/posthog/commit/b02d78db32d32f687265fd348aeb98ab9910d90f) feat(error-tracking): add error tracking alerts to the alerts platform — Thanks @hpouillot!
- [86a4cca6d76](https://github.com/PostHog/posthog/commit/86a4cca6d7663a459578be9132a313314bca63b0) chore(cli): count generated schema changes only where hog runs them — Thanks @rafaeelaudibert!
- [573ed146815](https://github.com/PostHog/posthog/commit/573ed146815aacdd3a724ca1900738d8de7fa1b1) feat(aio): support updates and deletes for offline evaluations — Thanks @Radu-Raicea!
- [c33e840e1ba](https://github.com/PostHog/posthog/commit/c33e840e1ba8fc9a5a50b4fcf63a538399aea233) feat(customer-analytics): tag customer tasks — Thanks @arthurdedeus!
- [5968b2e1ba6](https://github.com/PostHog/posthog/commit/5968b2e1ba68fa3350f75ecb8ef81ad60ebaffd2) chore(deps): upgrade to kea-typegen 3.9 and typescript 7.1 beta — Thanks @mariusandra!
- Changes built into hog since v0.1.0, from these pull requests:

  - [#138212](https://github.com/PostHog/posthog/pull/138212) fix(messaging): report only listed addresses as removed from suppressions
  - [#138661](https://github.com/PostHog/posthog/pull/138661) feat(releases): split area and release object flags
  - [#137271](https://github.com/PostHog/posthog/pull/137271) fix(warehouse-sources): record how setup was called in created_via
  - [#138705](https://github.com/PostHog/posthog/pull/138705) fix(signals): rank anomaly search's recent order by buckets ago
  - [#138293](https://github.com/PostHog/posthog/pull/138293) fix(mcp): keep an empty metric catalog answer for ten minutes
  - [#138072](https://github.com/PostHog/posthog/pull/138072) fix(mcp): unwrap stringified JSON objects in exec call input
  - [#136037](https://github.com/PostHog/posthog/pull/136037) feat(signals): let an opted-in scout start report actions
  - [#138905](https://github.com/PostHog/posthog/pull/138905) fix(data-modeling): leave models that don't compile out of a manual run
  - [#138967](https://github.com/PostHog/posthog/pull/138967) feat(signals): filter the inbox report list and mcp tool by tag
  - [#134901](https://github.com/PostHog/posthog/pull/134901) feat(signals): tell scouts who started a discussion on their report
  - [#138964](https://github.com/PostHog/posthog/pull/138964) feat(signals): add an if_updated_at precondition to scratchpad remember
  - [#138490](https://github.com/PostHog/posthog/pull/138490) feat(workflows): import resend contacts as people
  - [#139193](https://github.com/PostHog/posthog/pull/139193) feat(signals): let a scout be granted the resolve_conflicts report action
  - [#138975](https://github.com/PostHog/posthog/pull/138975) feat(signals): keep earlier versions of a scratchpad entry
  - [#138903](https://github.com/PostHog/posthog/pull/138903) fix(mcp): audit read-only hints on tools that need write scopes
  - [#139385](https://github.com/PostHog/posthog/pull/139385) feat(replay-vision): offer a scheduled scanner after on-demand scans
  - [#138968](https://github.com/PostHog/posthog/pull/138968) feat(signals): add a key_prefix filter to scout scratchpad search
  - [#139473](https://github.com/PostHog/posthog/pull/139473) fix(signals): sort anomaly search's recent order by flagged bucket end
  - [#139589](https://github.com/PostHog/posthog/pull/139589) chore(messaging): drop the beta flag from the supabase auth email mcp tools
  - [#139479](https://github.com/PostHog/posthog/pull/139479) perf(signals): remove the 30-day baseline window from anomaly search
  - [#139600](https://github.com/PostHog/posthog/pull/139600) feat(signals): tell scouts when a scratchpad key was expired or changed
  - [#139481](https://github.com/PostHog/posthog/pull/139481) fix(signals): report the anomaly search series cap
  - [#139519](https://github.com/PostHog/posthog/pull/139519) feat(endpoints): tag queries with execution id and enrich run logs
  - [#139550](https://github.com/PostHog/posthog/pull/139550) fix(endpoints): clean up never-called materializations, count oauth runs
  - [#139488](https://github.com/PostHog/posthog/pull/139488) feat(signals): hide noisy series from anomaly search by default
  - [#139667](https://github.com/PostHog/posthog/pull/139667) feat(signals): let agents add and remove inbox plan steps over mcp
  - [#139755](https://github.com/PostHog/posthog/pull/139755) feat(workflows): give new api email steps the editor's default sender
  - [#139696](https://github.com/PostHog/posthog/pull/139696) fix(signals): drop the rate order and return one checked-through time
  - [#139693](https://github.com/PostHog/posthog/pull/139693) fix(signals): apply a minimum range to weekly and monthly anomaly search
  - [#133544](https://github.com/PostHog/posthog/pull/133544) feat(visual-review): gate merges on the commit status in ledger mode
  - [#140181](https://github.com/PostHog/posthog/pull/140181) fix(mcp): check connection scopes before running a tool remotely
  - [#140236](https://github.com/PostHog/posthog/pull/140236) fix(mcp): give repair cdc the long-running api timeout
  - [#140036](https://github.com/PostHog/posthog/pull/140036) feat(signals): scope the anomalies tab to insights the person viewed
  - [#140007](https://github.com/PostHog/posthog/pull/140007) fix(workflows): say that sensitive emails keep click tracking
  - [#139952](https://github.com/PostHog/posthog/pull/139952) fix(workflows): leave step items out of the provider imports list
  - [#137917](https://github.com/PostHog/posthog/pull/137917) feat(data-warehouse): fill template variables in the s3 destination prefix
  - [#140296](https://github.com/PostHog/posthog/pull/140296) feat(stamphog): review a refused pr again when people answer it
  - [#140308](https://github.com/PostHog/posthog/pull/140308) chore(data-catalog): remove relationship proposal confidence
  - [#140113](https://github.com/PostHog/posthog/pull/140113) feat(workflows): import audiences, templates and campaigns from mailchimp
  - [#138007](https://github.com/PostHog/posthog/pull/138007) feat(data-warehouse): fill template variables in the azure blob destination prefix
  - [#140577](https://github.com/PostHog/posthog/pull/140577) feat(mcp): use the @posthog/brand logomark in MCP Apps
  - [#140435](https://github.com/PostHog/posthog/pull/140435) chore(aio): remove tagger pages, list API, and MCP tool
  - [#140479](https://github.com/PostHog/posthog/pull/140479) feat(error-tracking): check tag rules on every exception in a daily sweep

- [55ad009f3fa](https://github.com/PostHog/posthog/commit/55ad009f3fa9cbbd890cdf4c77280a3d81db0028) hog keeps the indentation and the trailing newline of posthog.json when it updates the file, as `hog auth login` and `hog schema pull` do. — Thanks @rafaeelaudibert!
- [242fdb4b8c0](https://github.com/PostHog/posthog/commit/242fdb4b8c00fc73fbe09383decbf7ade332ab5d) fix(mcp): remove deprecated recording_domains from project-settings-update — Thanks @ksvat!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(workflows): import suppressions and streams from postmark — Thanks @rafaeelaudibert!
- [78e3be909bf](https://github.com/PostHog/posthog/commit/78e3be909bff5b594277eaf72873ea6d002133c8) feat(alerts): store new insight alert destinations as rows only — Thanks @rafaeelaudibert!

## 0.1.0 — 2026-11-19

### Minor changes

- [579cf33c81a](https://github.com/PostHog/posthog/commit/579cf33c81a9cee95f035cbe5decbf98c1549715) Ship hog as a binary for macOS, Linux and Windows, with install scripts, the `hog` npm package and a Homebrew formula. — Thanks @rafaeelaudibert!

### Patch changes

- [0e1005fae6b](https://github.com/PostHog/posthog/commit/0e1005fae6bef0da7cee7a02841ab0d83242e709) feat(messaging): send a sandbox code send that sets from or reply_to — Thanks @Silthus!
