# hog

## 0.2.0 — 2026-11-25

### Minor changes

- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) hog now shows notices from PostHog after a command, such as a version reaching its end of support, with the update command for your install. They come in the release manifest and in PostHog API answers, so CI jobs with update checks off get them too. People see one line on stderr, agents get a JSON line, and GitHub Actions jobs also get an annotation on the run summary. — Thanks @rafaeelaudibert!

### Patch changes

- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(mcp): run a bare sql string sent to execute-sql as its query — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(mcp): keep the next-page hint on exec text results — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(dashboards): add dashboards v2 scene — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(mcp): split writes from exec so clients can always allow reads — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) hog keeps the indentation and the trailing newline of posthog.json when it updates the file, as `hog auth login` and `hog schema pull` do. — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(cli): tell agents when the user can approve a hog ci setup request — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(mcp): keep expected errors out of error tracking — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(stamphog): skip owner review requests on fully attested pull requests — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(mcp): remove deprecated recording_domains from project-settings-update — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) `hog error-tracking clone` and Hermes uploads now read, write and package sourcemaps in hog-worker, with the same Rust code posthog-cli runs. — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(workflows): warn api callers when a workflow is live on the test sender — Thanks @rafaeelaudibert!
- [09c358de247](https://github.com/PostHog/posthog/commit/09c358de2473e1881dc5d9ac7cb2b97c2ae8d4e8) feat(groups): expose group management to MCP — Thanks @thmsobrmlr!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(cli): make hog auth status easy for a person to scan — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(mcp): add organization-create tool — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(marketing-analytics): detect applied keyword gaps and brand negatives — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(workflows): let an email tool import ask for settings before it starts — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(cli): show people a short hog overview and add hog whoami — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) chore(deps): upgrade to kea-typegen 3.9 and typescript 7.1 beta — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(workflows): push message templates can be made transactional — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) chore(cli): count generated schema changes only where hog runs them — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(metrics): find metric attributes by their values — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(signals): let a person's agents work under their report claim — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(customer-analytics): tag customer tasks — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(signals): list recently ended monitoring reports with their outcome — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(signals): expire spend receipts after three months — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(signals): tell agents which inbox reports are free to take — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) chore(aio): remove the `llma-tagger-test-hog` tool — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) Every install of hog now includes hog-worker, the program that reads and writes build output for `hog error-tracking`, and `hog upgrade` and the install scripts replace the two together. On Alpine and other musl systems, the install script now names the missing `libstdc++` and `libgcc` packages when hog can't start without them. — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) chore(data-catalog): point agents at metric-list for catalog checks — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(signals): write task commits only to the reports they target — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) chore(deps): update posthog-node to 6.0.4 in nodejs and services/mcp — Thanks @rafaeelaudibert!
- [ed6c73fdb0c](https://github.com/PostHog/posthog/commit/ed6c73fdb0c5827f7c87c7521c33810e356cbd62) feat(signals): monitor pull request impact — Thanks @oliverb123!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(replay-vision): teach the agent tools a scanner scope — Thanks @rafaeelaudibert!
- [26721059792](https://github.com/PostHog/posthog/commit/26721059792616ed0014e1d2eeb18b2c864acacb) perf(mcp): cut the context agents spend on tool output and schemas — Thanks @richardsolomou!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(mcp): name more harnesses and drop structuredContent by default — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(marketing-analytics): mark recommendations applied when ads show the change — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(notebooks): add notebook app builder — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(business-knowledge): give libraries their own tab and page — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(mcp): run exec search patterns through a linear-time regex engine — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(workflows): publish preview says when it moves steps onto the test sender — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(cli): read only the xml entities in an info.plist — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(aio): support updates and deletes for offline evaluations — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) `hog error-tracking upload` now reads ELF files, Mach-O files and dSYM bundles in hog-worker, with the same Rust code posthog-cli runs. — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(auth): remove legacy team secret token paths — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) `hog error-tracking upload` and `process` now build JavaScript and ProGuard symbol sets in hog-worker, and `--delete-after` cleans up there too. The uploads and the files are the same, and a large build takes far less time and memory. — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(workflows): import suppressions and unsubscribe groups from sendgrid — Thanks @rafaeelaudibert!
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
  - [#138455](https://github.com/PostHog/posthog/pull/138455) feat(aeo): add an engine by topic mention heatmap to the overview
  - [#128489](https://github.com/PostHog/posthog/pull/128489) feat(conversations): let mcp clients attach images to ticket replies
  - [#140379](https://github.com/PostHog/posthog/pull/140379) fix(autoresearch): own the training launch gate
  - [#140699](https://github.com/PostHog/posthog/pull/140699) fix(review-hog): default the review trigger to a standard review
  - [#140517](https://github.com/PostHog/posthog/pull/140517) feat(notebooks): save sql results as warehouse tables and cohorts
  - [#141075](https://github.com/PostHog/posthog/pull/141075) fix(mcp): keep saved chart and alert grouping settings on update
  - [#141052](https://github.com/PostHog/posthog/pull/141052) feat(mcp): keep unknown keys in stored schema_ref params
  - [#141145](https://github.com/PostHog/posthog/pull/141145) chore(cli): release hog v0.1.1
  - [#140983](https://github.com/PostHog/posthog/pull/140983) feat(experiments): return draft health findings in the mcp launch result
  - [#141081](https://github.com/PostHog/posthog/pull/141081) feat(notebooks): version published app sources and input defaults
  - [#140978](https://github.com/PostHog/posthog/pull/140978) feat(autoresearch): add a monthly project training budget
  - [#140489](https://github.com/PostHog/posthog/pull/140489) feat(signals): add slack channel scouts to the inbox sources tab
  - [#141061](https://github.com/PostHog/posthog/pull/141061) feat(error-tracking): add an on-demand summarize action for issues
  - [#140709](https://github.com/PostHog/posthog/pull/140709) chore(aio): remove the tagger api scope and access-control resource
  - [#140689](https://github.com/PostHog/posthog/pull/140689) fix(warehouse-sources): run a manual sync of a failing table
  - [#140731](https://github.com/PostHog/posthog/pull/140731) feat(aeo): onboard ai visibility teams through the early-access flag
  - [#127296](https://github.com/PostHog/posthog/pull/127296) feat(workflows): let agents set up an email sending domain via mcp
  - [#140710](https://github.com/PostHog/posthog/pull/140710) feat(data-warehouse): record when a sync last checked its source
  - [#141585](https://github.com/PostHog/posthog/pull/141585) chore(cli): release hog v0.2.0
  - [#141667](https://github.com/PostHog/posthog/pull/141667) feat(signals): leave records emission skips out of the filter preview
  - [#141292](https://github.com/PostHog/posthog/pull/141292) feat(marketing-analytics): judge recommendations by posthog conversions
  - [#141666](https://github.com/PostHog/posthog/pull/141666) feat(signals): preview a source filter with unsaved team scope
  - [#139762](https://github.com/PostHog/posthog/pull/139762) feat(warehouse): remove stale synced person properties
  - [#141790](https://github.com/PostHog/posthog/pull/141790) fix(workflows): drop delivery_rate from the infrastructure health api
  - [#128558](https://github.com/PostHog/posthog/pull/128558) feat(experiments): filter shared metrics by creator, tags and type
  - [#141274](https://github.com/PostHog/posthog/pull/141274) feat(warehouse-suggestions): stop refreshes without deprecating a view
  - [#141574](https://github.com/PostHog/posthog/pull/141574) fix(mcp): keep the metric catalog answer for an hour
  - [#140706](https://github.com/PostHog/posthog/pull/140706) fix(mcp): restore the warehouse health tool and fix guessed tool names
  - [#140768](https://github.com/PostHog/posthog/pull/140768) fix(data-warehouse): show webhook tables whose events are dropped
  - [#142047](https://github.com/PostHog/posthog/pull/142047) feat(notebooks): add multi-select dropdowns to notebook apps
  - [#141969](https://github.com/PostHog/posthog/pull/141969) fix(aio): cap the events query-llm-trace reads on large traces
  - [#140720](https://github.com/PostHog/posthog/pull/140720) feat(aio): support project keys for datasets, evaluations, and scores
  - [#142117](https://github.com/PostHog/posthog/pull/142117) feat(signals): filter a report's artefacts by type

- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(error-tracking): add error tracking alerts to the alerts platform — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(replay-vision): accept a scanner scope on the API — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(workflows): import bounces, complaints, unsubscribes and lists from mailgun — Thanks @rafaeelaudibert!
- [318fd3af3cd](https://github.com/PostHog/posthog/commit/318fd3af3cd1d4748506b37c1c0a1a4a32ccfa0b) `schema pull` and `endpoints pull` now write only inside the project, and hog won't write through a `posthog.json` link. `error-tracking` commands refuse folders in `errorTracking.sources` outside the project, and never open a sourcemap outside the selected paths. Pass a folder outside the project on the command line. — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(aeo): filter ai visibility by a date range — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(messaging): schedule a send up to 7 days ahead behind a flag — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(workflows): import suppressions and streams from postmark — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) chore(cli): give hog the typescript compiler api — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) `hog error-tracking inject` now rewrites bundles and sourcemaps in hog-worker, a Rust program that ships next to hog. The files it writes are the same, and a large build takes far less time and memory. — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(alerts): store new insight alert destinations as rows only — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(dashboards): read the first screen through cached_tiles on first load — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) hog's usage events now say how hog was installed, such as Homebrew, the install script, a global npm install, `npx` or a project dependency. They never include the path. — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) fix(alerts): write moved insight alert edits to the platform copy only — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) chore(aio): remove offline evaluations feature flag — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(error-tracking): add an issue tag rules api — Thanks @rafaeelaudibert!
- [4f4d0f70c79](https://github.com/PostHog/posthog/commit/4f4d0f70c7921500da7004d83c5dab29cdad44be) feat(workflows): add MCP tools for workflow email sends and recipient activity — Thanks @rafaeelaudibert!
- [f93c5eaea94](https://github.com/PostHog/posthog/commit/f93c5eaea94205462272f7e2686f675a0585af59) Links to an OAuth application can now point to its own settings page, where its provisioning review lives. — Thanks @rafaeelaudibert!

## 0.1.0 — 2026-11-19

### Minor changes

- [579cf33c81a](https://github.com/PostHog/posthog/commit/579cf33c81a9cee95f035cbe5decbf98c1549715) Ship hog as a binary for macOS, Linux and Windows, with install scripts, the `hog` npm package and a Homebrew formula. — Thanks @rafaeelaudibert!

### Patch changes

- [0e1005fae6b](https://github.com/PostHog/posthog/commit/0e1005fae6bef0da7cee7a02841ab0d83242e709) feat(messaging): send a sandbox code send that sets from or reply_to — Thanks @Silthus!
