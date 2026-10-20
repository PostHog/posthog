# Ordered image releases

Use this reference when reusing the common ordered alias helper or the shared-image policy and binding APIs. A common Git repository or registry does not establish a shared artifact.

## Current capability

The common alias uses `.github/scripts/ordered-image-release.sh`. `.github/actions/paths-filter` owns canonical manifest schema loading in `src/shared-image-policy.ts` and legacy projection. `.github/actions/shared-image-releases` owns `inspect`, `publish`, approved publication bindings, the interval adapter and fingerprint APIs. It imports the loader and vendored matcher from paths-filter. The new action has no Depot mirror. Channels stay empty until separately reviewed activation; manifest entries must resolve to approved destinations.

## Common ordered alias

After a successful default-branch build, reuse the helper under the repository-owner, `CD_DEPLOY_ENABLED` and `ORDERED_IMAGE_ALIAS_PAUSED` gates from `ordered_image_alias` in `.github/workflows/container-images-cd.yml`. Keep one active production publisher during switchover or rollback.

Run `bash .github/scripts/ordered-image-release.sh tag` in the executing checkout with `GITHUB_SHA` equal to the built revision. It writes `tag` to `GITHUB_OUTPUT`, preserving first-parent ordering and `r<12-digit ordinal>-<sha6>`. A shallow checkout fetches complete history from its configured origin. Missing history yields a warning and no tag; surface that result as the common caller does.

Install the pinned, checksum-verified client with `bash .github/scripts/ordered-image-release.sh install "$RUNNER_TEMP/regctl"`. After approved registry authentication, run the helper's `publish` command:

| Environment                      | Meaning                                                                 |
| -------------------------------- | ----------------------------------------------------------------------- |
| `REGCTL`                         | Checksum-verified copy client path                                      |
| `EXPECTED_DIGEST`                | Exact successful-build digest                                           |
| `ECR_REGISTRY`, `ECR_REPO`       | Approved destination and ECR readback repository                        |
| `SOURCE_REGISTRY`, `SOURCE_REPO` | Supply both for an approved source, or omit both to use the destination |
| `ORDERED_ALIAS`                  | Computed ordered tag                                                    |
| `GITHUB_OUTPUT`                  | Optional helper `outcome`; the common step does not consume it          |

The helper skips publication with a warning if the build digest, destination registry or destination repository is empty, or if only one source coordinate is supplied. The caller authenticates for the approved account and region. Pinned regctl `image copy` preserves single manifests, indexes and in-index attestations without listing external referrers. Exact ECR readback queries the destination account, repository and alias tag. The common caller retains its 40-second copy/readback defaults and five-minute job budget. Selective publication supplies separately measured `COPY_TIMEOUT_SECONDS` and `READBACK_TIMEOUT_SECONDS`; both require positive integer seconds up to 999.

Only `present-at-expected-digest` establishes publication. `absent`, `integrity-mismatch` and `unknown` do not. A copy error can reconcile to exact presence; a successful copy can have unknown readback. The common publish step has no `id` and does not consume the helper's `outcome` output. A green fail-soft job or an annotation does not prove publication. Same-digest reruns reconcile, while immutable conflicts retain their mismatch outcome. Never copy publisher/readback shell per service.

Image annotations and consumer `source.repo` keep canonical `PostHog/posthog` identity. History and policy evaluation use the actual workflow checkout and built SHA. Fetch from that checkout's configured origin, never from an endpoint derived from the canonical annotation. Missing executing history is an explicit failure, not unrelated input. Images built in their own repositories retain their existing publisher family.

## Canonical policy and approved bindings

Move each reused filter into `.github/shared-image-releases.yaml` once. The legacy action's `shared-image-policy` input calls `loadPolicy(text)` and `projectLegacyFilters(policy, inlineYaml)`. Preserve legacy endpoint comparisons, output names, ordering and compound dispatch conditions, including Python dependency analysis and coverage-added checks.

Keep a `dataWarehouse: null` reference at that rule's original inline position. The projection fills it from the manifest while preserving every non-null inline rule. Unresolved references fail; nonempty duplicate definitions are rejected. Metadata's ten-pattern historical fixture remains distinct from the broader active `dataWarehouse` rule and is not an active channel.

Version 1 has `version`, `filters` and `images`; images contain `channels`. Each channel has `repository`, `filter` and optional `bootstrapPolicyDigest`. `loadPolicy` validates the closed shape, references, positive patterns and nonempty channel status qualifiers limited to `added`, `modified` and `deleted`. The vendored matcher owns extglob/negation semantics; legacy-only veto and status rules retain prior behavior. Structural validation does not authorize publication.

`bindChannels(policy, approved)` validates a caller-supplied approved map. The caller builds that map from existing workflow and infrastructure configuration, never from the manifest. It returns approved destination bindings keyed by image and channel, including owner, repository, registry and replicas. Reuse those resolved bindings instead of selecting destinations again. Manifest entries cannot authorize destinations or redirect credentials; source/destination equality and regional collisions fail.

Run `.github/actions/shared-image-releases` with `shared-image-operation: inspect`. Supply `shared-image-repository`, `shared-image-registry` and `shared-image-destination-registry` from approved workflow configuration, and `shared-image-destinations` as the infrastructure-approved JSON array. `shared-image-policy` defaults to `.github/shared-image-releases.yaml`; `working-directory` selects the executing checkout. Inspect validates and resolves the bindings before emitting the `channels` presence flag and the `bindings` JSON map. That output describes configuration, not publication outcomes. It performs no publication and does not parse force or bootstrap requests. In `container-images-cd.yml`, inspect reads `SHARED_IMAGE_REGISTRY`, `SHARED_IMAGE_DESTINATION_REGISTRY` and `SHARED_IMAGE_DESTINATIONS` from repository variables before publisher authentication. Configure those values together from approved infrastructure. ECR login occurs only after inspect finds a channel. Publish checks the login registry against the approved destination configuration before any copy. Do not derive approvals from the manifest.

The publisher validates the source policy and approved publication destinations. The Charts migration helper owns consumer binding for new-service onboarding and existing-service migration. Hand source identity, policy and destination coordinates to Charts. The helper checks owner, lane, image group, repositories, regional replicas and inherited Git filters against the resolved Charts consumer. Obtain that check before treating the consumer setup as ready.

Temporal worker release repositories use descriptive provisioned paths under `posthog-temporal-workers/`, such as `posthog-temporal-workers/data-warehouse-metadata`; `posthog-temporal-workers/batch-exports-sync` is the reserved sibling example. Preserve domain words and omit redundant `temporal-worker-` prefixes. Other workload classes choose their own namespace; the publisher does not infer workload identity from that prefix. Preserve bare tags, full revision/digest identity and source annotations. Changing repositories changes workload image strings and causes a rollout even at an equal digest.

## Interval and fingerprint APIs

The internal `.github/actions/shared-image-releases/src/shared-image.ts` entry point exports `intervalFiles`, `Filter` and the policy/binding APIs. Call `intervalFiles(base, revision, git)` with the asynchronous Git runner owned by `SourceHistory`; it applies measured command deadlines, output bounds and `GIT_NO_LAZY_FETCH=1`. The adapter and publisher share `assertFirstParent` and checkout validation. Reuse paths-filter's dependency-free Git diff parser; importing its process helpers also imports their action dependencies. Keep Git asynchronous so history comparisons cannot stall registry timers or output draining. The interval adapter validates the executing checkout and complete history, bounds first-parent membership to the interval, includes merge deltas, treats renames as add/delete and maps Git typechanges to modified. Missing history, invalid frontiers and exhausted bounds fail explicitly. Match the returned files with `Filter.match`; legacy dispatch still compares endpoints. Newline filenames remain intact, although the pinned engine does not match them with `worker/**`.

Use `serializePolicy` and `policyDigest` for one fingerprint format. Canonical UTF-8 JSON retains authored array order, status objects, vetoes, Unicode and literal `<>&`, with sorted object keys and no trailing newline. Reordering a list changes its fingerprint. A digest does not authorize a destination binding.

## Selective publication

Keep the common ordered alias attempt first. The selective job depends on its completion and the successful build, so an earlier common-job failure does not silently suppress channel work. Preserve the repository-owner, default-branch, `CD_DEPLOY_ENABLED` and existing pause gates. A failed or skipped build never invokes the publisher. When channels exist but no ordered tag is generated, the selective job emits an error and fails within its existing fail-soft job boundary; inspect the tag step before retrying.

For each resolved channel destination, list every registry page and select the greatest visible tag matching the complete bare ordered-alias grammar. Resolve its digest and full canonical source revision, then validate its ordinal and executing first-parent membership. Malformed identity or missing history blocks that channel. Never use the common repository frontier, push boundary, build marker or deployed revision as the channel baseline. Older builds skip; equal-revision reruns report `present` at the expected digest and block with `integrity-mismatch` at a different digest.

Before comparing paths, batch-fetch missing interval trees from the executing checkout's configured origin within the fetch budget. Missing trees after bounded fetching block publication. A failed availability probe retains its cause alongside any fetch error. Match every entry after the channel frontier through the successful build with that channel's filter at the build revision. This recovers relevant changes from failed or skipped earlier builds. Compare effective policy fingerprints at every policy change in the interval, including reverted changes. Other channels' changes do not qualify this channel, and historical destination rebinding is rejected.

A qualifying channel copies the exact built digest from the paired common source coordinates to its resolved destination with the existing helper. Results persist in `shared-image-releases/results.json` and per-channel logs. `published` records a new verified publication; `present` records an existing exact publication. Only `present-at-expected-digest` establishes a baseline. `absent`, `integrity-mismatch` and `unknown` remain blocked, and helper crashes, timeouts or missing outcome lines retain their primary reason. One blocked channel does not stop other workers.

Invoke `container-images-cd.yml` through `workflow_dispatch` on the default branch. Supply `shared-image-force` as a JSON array of configured image/channel keys, or `shared-image-bootstrap` as the reviewed seed object described below. Force qualifies unmatched paths but cannot bypass image identity, history or destination rules. Request validation belongs to `publish`.

## Bootstrap and activation

Ordinary publication refuses an empty ordered frontier. Review one seed revision and exact digest, then supply `shared-image-bootstrap` as a JSON object with `channel`, `revision` and `digest`. Bootstrap and force cannot be combined, and a seed newer than the executing revision is refused. Exact readback writes a bootstrap receipt with approved coordinates, current policy revision and fingerprint, seed revision, ordinal, tag, digest and outcome.

Retry the same seed after newer aliases arrive. The seed must still exist at its expected digest; a missing seed in a nonempty repository or a conflicting digest fails. When the seed predates the channel policy, carry `bootstrapPolicyDigest` in the channel and verify it equals the reviewed current fingerprint before seeding. Preserve that adoption fingerprint across later policy changes.

Before adding the first channel, review approved repository variables, credentials, source reads, destination writes and listing, immutable tags, regional replicas, retention and bootstrap evidence. Obtain the Charts consumer-binding check and verify consumer pulls and release selection separately. Adding a repository can cause a rollout even at the same digest. This publisher makes no consumer or Charts changes.

## Bound work before activation

The workflow allows four channels and two concurrent registry workers. A local representative run covers 48 first-parent commits and the full four-channel fan-out; it measures fixture work, not production upload throughput. Recheck these bounds before increasing fan-out or enabling a destination with slower copy or replication behavior.

| Work                           | Bound              |
| ------------------------------ | ------------------ |
| Tree and policy fetching       | 60 seconds         |
| History comparison             | 30 seconds         |
| Combined command output        | 64 MiB             |
| Registry operation             | 15 seconds         |
| Selective copy and readback    | 120 and 30 seconds |
| Channel registry work          | 300 seconds        |
| Action total                   | 720 seconds        |
| Publish step and selective job | 13 and 18 minutes  |

Commands kill their process group on timeout or output exhaustion. Bounded fetching, unavailable trees and registry timeouts must leave blocked channels unadvanced. The independent common job retains its own attempt and budget. Activation must verify real fallback copy times, replica visibility, quiet intervals and retained rollback images.

This guidance grants no publication, infrastructure apply, cluster operation or rollout authority.
