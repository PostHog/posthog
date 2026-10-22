# Ordered image releases

Use this reference when reusing the common ordered alias helper or the shared-image policy and binding APIs. A common Git repository or registry does not establish a shared artifact.

## Current capability

The common alias uses `.github/scripts/ordered-image-release.sh`. `.github/actions/paths-filter` owns canonical manifest schema loading in `src/shared-image-policy.ts` and legacy projection. `.github/actions/shared-image-releases` owns `inspect`, source publication bindings, the interval adapter and fingerprint APIs. Channels must stay empty; selective worker publication is not implemented. A manifest entry does not create a publisher.

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

The helper skips publication with a warning if the build digest, destination registry or destination repository is empty, or if only one source coordinate is supplied. The caller authenticates for the approved account and region. Pinned regctl `image copy` preserves single manifests, indexes and in-index attestations without listing external referrers. Exact ECR readback queries the destination account, repository and alias tag. The common caller retains its 40-second copy/readback bounds and five-minute job budget.

Only `present-at-expected-digest` establishes publication. `absent`, `integrity-mismatch` and `unknown` do not. A copy error can reconcile to exact presence; a successful copy can have unknown readback. The common publish step has no `id` and does not consume the helper's `outcome` output. A green fail-soft job or an annotation does not prove publication. Same-digest reruns reconcile, while immutable conflicts retain their mismatch outcome. Never copy publisher/readback shell per service.

Image annotations and consumer `source.repo` keep canonical `PostHog/posthog` identity. History and policy evaluation use the actual workflow checkout and built SHA. Fetch from that checkout's configured origin, never from an endpoint derived from the canonical annotation. Missing executing history is an explicit failure, not unrelated input. Images built in their own repositories retain their existing publisher family.

## Canonical policy and origin bindings

Move each reused filter into `.github/shared-image-releases.yaml` once. The legacy action's `shared-image-policy` input calls `loadPolicy(text)` and `projectLegacyFilters(policy, inlineYaml)`. Preserve legacy endpoint comparisons, output names, ordering and compound dispatch conditions, including Python dependency analysis and coverage-added checks.

Keep a `dataWarehouse: null` reference at that rule's original inline position. The projection fills it from the manifest while preserving every non-null inline rule. Unresolved references fail; nonempty duplicate definitions are rejected. Metadata's ten-pattern historical fixture remains distinct from the broader active `dataWarehouse` rule and is not an active channel.

Version 1 has `version`, `filters` and `images`; images contain `channels`. Each channel has `repository`, `filter` and optional `bootstrapPolicyDigest`. `loadPolicy` validates the closed shape, references, positive patterns and nonempty channel status qualifiers limited to `added`, `modified` and `deleted`. The vendored matcher owns extglob/negation semantics; legacy-only veto and status rules retain prior behavior. Structural validation does not authorize publication.

`bindChannels(policy, sourceRepository)` validates the configured build input, rejects duplicate origin repositories and rejects a destination equal to the common source. The canonical loader validates repository paths against the supported ECR grammar. The resolved map is keyed by image and channel, with `{repository}` values. There is no destinations map, publisher owner label or replica list. IAM authorizes writes to provisioned repositories; the publisher does not create them.

Run `.github/actions/shared-image-releases` with `shared-image-operation: inspect` and `shared-image-repository` from workflow configuration. `shared-image-policy` defaults to `.github/shared-image-releases.yaml`; `working-directory` selects the executing checkout. Inspection runs offline and emits `channels` and the repository-only `bindings` map. It needs no registry hostname or destinations input. Empty channels require no authentication or registry calls. The action imports the loader and matcher from paths-filter by relative source path; do not copy either module.

The source action validates policy offline. IAM authorizes origin writes and ECR handles replication; an origin receipt cannot establish regional readiness. The Charts migration helper owns consumer binding for new-service onboarding and existing-service migration. Hand source identity, policy and destination coordinates to Charts. Charts checks resolved regional repositories against source policy and provisioned infrastructure, together with owner, lane, image group and inherited Git filters. Kargo checks regional tag, revision and digest agreement. Obtain that check before treating the consumer setup as ready.

Temporal worker release repositories use descriptive provisioned paths under `posthog-temporal-workers/`, such as `posthog-temporal-workers/data-warehouse-metadata`; `posthog-temporal-workers/batch-exports-sync` is the reserved sibling example. Preserve domain words and omit redundant `temporal-worker-` prefixes. Other workload classes choose their own namespace; the publisher does not infer workload identity from that prefix. Preserve bare tags, full revision/digest identity and source annotations. Changing repositories changes workload image strings and causes a rollout even at an equal digest.

## Interval and fingerprint APIs

The internal `.github/actions/shared-image-releases/src/shared-image.ts` entry point exports `intervalFiles`, `Filter` and the policy/binding APIs. Supply `timeoutMs` and `maxBuffer` to bind measured budgets before dispatch. The interval adapter validates the executing checkout and complete history, bounds first-parent membership to the interval, includes merge deltas, treats renames as add/delete and maps Git typechanges to modified. Missing history, invalid frontiers and exhausted bounds fail explicitly. Match the returned files with `Filter.match`; legacy dispatch still compares endpoints. Newline filenames remain intact, although the pinned engine does not match them with `worker/**`.

Use `serializePolicy` and `policyDigest` for one fingerprint format. Canonical UTF-8 JSON retains authored array order, status objects, vetoes, Unicode and literal `<>&`, with sorted object keys and no trailing newline. Reordering a list changes its fingerprint. A digest does not authorize a destination binding.

This guidance grants no publication, infrastructure apply, cluster operation or rollout authority.
