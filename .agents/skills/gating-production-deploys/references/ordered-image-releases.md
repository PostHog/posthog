# Ordered image releases

Use this reference for a new monorepo publisher or independent releases of consumers sharing one successful image build. A common Git repository or registry does not establish a shared artifact.

## Foundation and pending integration

The foundation supplies `.github/scripts/ordered-image-release.sh`, the canonical `.github/shared-image-releases.yaml` loader, a legacy projection, the vendored matcher adapter and one fingerprint serializer. The common alias uses the shared helper; worker channels remain empty.

Selective worker publication is pending in the next integration PR. That PR supplies destination frontier discovery, cumulative policy comparison, explicit bootstrap and force invocations, bounded history preparation and fan-out, and failure isolation. Adding a manifest entry alone cannot enable those capabilities. Consumer repository values already support separate repositories, but do not supply selective source publication.

## Dedicated monorepo images

After a successful default-branch build, reuse the helper under the repository-owner, `CD_DEPLOY_ENABLED` and `ORDERED_IMAGE_ALIAS_PAUSED` gates from `ordered_image_alias` in `.github/workflows/container-images-cd.yml`. Keep one active production publisher during switchover or rollback.

Run `bash .github/scripts/ordered-image-release.sh tag` in the executing checkout with `GITHUB_SHA` equal to the built revision. It writes `tag` to `GITHUB_OUTPUT`, preserving first-parent ordering and `r<12-digit ordinal>-<sha6>`. Missing history yields a warning and no tag; surface that result as the common caller does.

Install the pinned, verified client with `bash .github/scripts/ordered-image-release.sh install "$RUNNER_TEMP/regctl"`. After approved registry authentication, run the helper's `publish` command:

| Environment                      | Meaning                                                                    |
| -------------------------------- | -------------------------------------------------------------------------- |
| `REGCTL`                         | Checksum-verified copy client path                                         |
| `EXPECTED_DIGEST`                | Exact successful-build digest                                              |
| `ECR_REGISTRY`, `ECR_REPO`       | Approved destination and ECR readback repository                           |
| `SOURCE_REGISTRY`, `SOURCE_REPO` | Optional approved source, defaulting to the destination for a common alias |
| `ORDERED_ALIAS`                  | Computed ordered tag                                                       |
| `GITHUB_OUTPUT`                  | Receives explicit `outcome`                                                |

The caller authenticates for the approved account and region. The helper uses pinned regctl `image copy --referrers` and exact ECR digest readback. It preserves single manifests, indexes and embedded attestations. External referrers need qualification if the actual build requires them. The common caller retains its 40-second copy/readback bounds and five-minute job budget. Worker budgets must cover upload fallback and require integration measurements.

Only `present-at-expected-digest` establishes publication. `absent`, `integrity-mismatch` and `unknown` do not. A copy error can reconcile to exact presence; a successful copy can have unknown readback. A green fail-soft job or an annotation is not a receipt. Same-digest reruns reconcile, while immutable conflicts retain their mismatch outcome. Never copy publisher/readback shell per service.

Image annotations and consumer `source.repo` keep canonical `PostHog/posthog` identity. History and policy evaluation use the actual workflow checkout and built SHA, including commits not yet exposed publicly. Fetch from that checkout's configured origin, never from an endpoint derived from the canonical annotation. Missing executing history is an explicit failure, not unrelated input.

Images built in their own repositories retain their existing shared-actions publisher family. This reference does not extend selective publishing to those implementations.

## Shared-image policy and consumer handoff

Recover the complete controlling dispatch condition and filter at an immutable source revision. For removed dispatches, recover the exact removal-parent rule. Metadata's ten-pattern historical rule is distinct from the current broader `dataWarehouse` rule and remains owner-review input. Do not activate examples or silently expand coverage.

Keep static paths plus Python dependency analysis, path-list additions and coverage-added conditions visible until accurately supported or explicitly changed. A policy digest cannot substitute for those other branches.

Move each reused filter into `.github/shared-image-releases.yaml` once. The legacy action's `shared-image-policy` input validates the manifest and merges its `filters` projection with remaining inline rules, rejecting duplicate names. Preserve legacy endpoint comparisons, output names and compound conditions. Consumer values contain repository coordinates, never another path list.

Keep a `dataWarehouse: null` reference at that rule's original inline position when moving its list. The projection fills the reference from the manifest, preserving legacy output ordering. Unresolved references fail; nonempty duplicate definitions are rejected.

Version 1 has `version`, `filters` and `images`; images contain `channels`. Each channel has `repository`, `filter` and optional `bootstrapPolicyDigest`. Channels require positive patterns and supported nonempty status entries after alias resolution. The vendored matcher owns extglob/negation semantics; legacy-only veto rules retain prior behavior.

Supply approved source/image coordinates and destination bindings from existing workflow and infrastructure configuration to `loadPolicy`. Manifest entries cannot authorize destinations or redirect credentials. `validateConsumerBinding` checks the owner, `ordered-image-v2` lane, single logical image group and all regional coordinates. Report conflicting inherited Git filters with their defining files/fields. Group members share one policy; independent policy owners cannot share a destination.

Temporal worker release repositories use descriptive provisioned paths under `posthog-temporal-workers/`, such as `posthog-temporal-workers/data-warehouse-metadata`; `posthog-temporal-workers/batch-exports-sync` is the reserved sibling example. Preserve domain words and omit redundant `temporal-worker-` prefixes. Other workload classes choose their own namespace; the publisher does not infer workload identity from that prefix. Preserve bare tags, full revision/digest identity and source annotations. Changing repositories changes workload image strings and causes a rollout even at an equal digest.

## Integration and activation

The next PR must attempt the common alias before worker history work and keep channel failures independent. Reuse first-parent deltas, including merge deltas, rename-as-add/delete and repeated paths with distinct statuses. Never substitute endpoint or last-push comparison. Newline filenames stay intact; the pinned engine still does not match them with `worker/**`.

Both bootstrap verification and every historical policy comparison must use `policyDigest` and its `serializePolicy`. Canonical UTF-8 JSON retains authored array order, status objects, vetoes, Unicode and literal `<>&`, with sorted object keys and no trailing newline. List reordering changes the fingerprint. Missing history or malformed policy blocks comparison; fingerprints never authorize rebinding.

Ordinary selective publication recovers relevant changes since that destination's last verified eligible image, including failed/skipped builds and later reverts. Empty destinations require one approved seed. Exact seed retries tolerate newer ordinary releases; bootstrap requires no fleet-wide pause. Force is an explicit list of known channels, bypassing relevance only. External dependency or base-image updates may need intentional publication. The foundation supplies no force interface.

Hand off the approved policy, successful-build identity, provisioned origin and all replicas, publisher/pull IAM, immutability, encryption/mount settings, lifecycle policy and preview, one seed and supported hold/rollback bounds. Metadata's proposal retains 1,000 ordered images per region with separate 14-day orphan cleanup; other consumers need their own count. Count retention guarantees neither arbitrary Stage holds nor fixed rollback days.

Normal activation verifies exact first-publication digest, replica arrival and consumer pull. Local registry tests do not qualify live ECR configuration. Before switching consumers, hold affected Stages under the existing attended procedure and compare the actual first Freight, selected Application, source revision, tag/digest and every replica with the approved baseline. Missing matching Freight or newer content requires resolution or explicit approval of a revised image/render diff. Seed readback alone is not promotion approval. Retain original-repository rollback images and restore prior automation only after accepted first-promotion evidence.

This guidance grants no publication, infrastructure apply, cluster operation or rollout authority.
