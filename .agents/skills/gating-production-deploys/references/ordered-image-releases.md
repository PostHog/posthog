# Ordered image releases

Use this reference for an independent release channel of the common built image. A shared Git repository or registry does not establish a shared artifact. Services with their own builds retain their existing publisher family.

## Common alias and selective channels

The common alias job in `.github/workflows/container-images-cd.yml` runs first. The dependent `shared_image_channels` job then evaluates `.github/shared-image-releases.yaml` through the vendored paths-filter action's `shared-image-operation` input. `inspect` checks configured channel keys; `publish` resolves destinations, compares history and copies eligible releases. Keep the repository-owner, successful-build, default-branch, `CD_DEPLOY_ENABLED` and `ORDERED_IMAGE_ALIAS_PAUSED` gates. Force and bootstrap use the normal authorized manual workflow invocation on the default branch and preserve every gate.

Both jobs call `.github/scripts/ordered-image-release.sh publish`. Supply the successful build's exact digest and the normal bare `r<12-digit ordinal>-<sha6>` tag. Keep canonical `PostHog/posthog` source annotations, full revision identity and unchanged image bytes. The executing checkout supplies history, including revisions not yet exposed by its public mirror. Fetch only from that checkout's configured origin.

The helper installs pinned, checksum-verified regctl v0.11.6 and uses plain `image copy`. This preserves manifests, indexes and in-index attestations. Do not claim external referrer support. Give `SOURCE_REGISTRY` and `SOURCE_REPO` together for a copy from the approved common image replica. Omitting both retains the common caller's same-repository behavior. Give the resolved destination as `ECR_REGISTRY` and `ECR_REPO`, and set `EXPECTED_DIGEST`, `ORDERED_ALIAS` and `REGCTL`. Missing required inputs warn and skip. An empty helper output never establishes publication.

Only `present-at-expected-digest` establishes publication. `absent`, `integrity-mismatch` and `unknown` leave the channel blocked. An uncertain copy can reconcile to exact presence; a successful copy with unavailable readback remains unknown. A green fail-soft job or an annotation is not a receipt. Immutable conflicts never authorize replacement content. The action retains per-channel results, and one channel's failure does not suppress other attempts or the earlier common alias.

## Policy and approved destinations

Version 1 has `version`, `filters` and `images`. Images contain `channels`; channels contain `repository`, `filter` and optional `bootstrapPolicyDigest`. Define reused filters once. The legacy action's `shared-image-policy` input calls the same loader and projects those filters into inline null references at their original positions. Preserve legacy endpoint comparisons, output order and compound dispatch conditions. Metadata's historical filter remains distinct from the broader active warehouse filter.

The workflow builds the approved map with `approvedImages` from its common repository setting, ECR login output and the separate `SHARED_IMAGE_DESTINATIONS` repository variable. That variable is an infrastructure-reviewed JSON array of `owner`, `repository`, `registry` and `replicas`. Each origin registry must equal the authenticated login output. The policy cannot authorize or redirect a destination. `bindChannels` validates every configured destination before any channel copy, names unknown inputs and returns the bindings the publisher consumes.

The workflow assumes `AWS_ECR_TEMPORAL_WORKERS_PUBLISH_IAM_ROLE` for channel copies. Configure that variable from the provisioned shared publisher output, keeping common publication credentials unchanged. The approved source is the common image replica in the destination registry. Its exact built digest and canonical metadata must be available within the registry budget. A lagging or absent replica blocks the affected copy rather than selecting another image.

Consumer owner, lane, image-group, repository, replica and inherited-filter checks belong to the consumer repository. Do not add a consumer validator to the publisher. Temporal workers use provisioned descriptive paths such as `posthog-temporal-workers/data-warehouse-metadata`. The publisher does not infer workload identity from that prefix.

## Frontier and interval

List the channel's destination with complete pagination. Choose the greatest tag matching the anchored bare ordered-tag grammar. Validate its exact digest, canonical source annotation, full revision, SHA fragment and first-parent ordinal. Malformed frontier metadata blocks comparison; it never selects an older fallback. Empty ordinary channels require explicit bootstrap.

Use this verified revision as B and the successful build as S. An equal revision verifies the existing alias. A validated newer frontier skips an older build. Otherwise require B on S's first-parent chain, obtain all required trees in bounded batches, then call `intervalFiles(B, S, budgets)` with lazy fetching disabled. Evaluate every first-parent delta using S's selected channel filter and the existing matcher. Include merge deltas and repeated paths with distinct statuses. A failed or skipped relevant build remains eligible in the next successful interval, including a later unrelated commit. Never substitute a push endpoint, deployed revision or global frontier for B. Native lexical selection retains a greater alias when concurrent lower publication finishes later.

Compare this channel's effective policy at B and every policy transition through S. Any change qualifies, including a change reverted before S. Unrelated channel changes do not qualify it. Reuse `policyDigest` for both interval comparisons and bootstrap. It hashes canonical UTF-8 JSON with sorted object keys, authored list order, status mappings, vetoes and literal Unicode and `<>&`. Missing or malformed historical input blocks comparison. A repository rebind requires a new reviewed adoption.

For a deliberate release without matching paths, dispatch the workflow with `shared-image-force` as a JSON array of explicit `image/channel` keys. Unknown keys and implicit wildcards fail. Force bypasses relevance only. It cannot bypass build success, history, image identity, immutability or ordinal checks. Path filters do not detect every external dependency or base-image security update; use this manual release path for those changes.

The publisher validates the source policy and approved publication destinations. The Charts migration helper owns consumer binding for new-service onboarding and existing-service migration. Hand source identity, policy and destination coordinates to Charts. The helper checks owner, lane, image group, repositories, regional replicas and inherited Git filters against the resolved Charts consumer. Obtain that check before treating the consumer setup as ready.

## One-seed bootstrap

Dispatch the default-branch workflow with `shared-image-bootstrap` containing one `channel`, full seed `revision` and exact seed `digest`. Use an approved successful build already available at the source coordinate. Ordinary channels refuse empty destinations. Bootstrap accepts an empty destination, derives the seed's ordinal from verified executing history, validates image identity and uses the same publish/readback helper.

A retry in a nonempty destination succeeds only when the approved seed tag still resolves to its expected digest. Newer ordinary aliases may exist. A missing seed or conflicting digest fails for explicit reconciliation. Existing exact seed content can be verified without the original source image. No fleet pause, drain, common-frontier freeze or second seed is involved.

When the seed predates the manifest or this channel, configure `bootstrapPolicyDigest` with the reviewed current policy fingerprint. Bootstrap verifies it before seeding. Ordinary comparison uses that immutable fingerprint until this channel first has a historical policy, then observes real policy transitions. Introducing the same matching policy alone does not release an image. Preserve the adoption fingerprint through later policy changes.

Successful bootstrap writes a versioned receipt under `shared-image-releases/bootstrap/<image>/<channel>.json`, with canonical source, source image, resolved destination and replicas, policy revision and digest, seed revision, ordinal, tag, image digest and exact readback outcome. The workflow uploads this with channel results. The receipt proves seed presence. It is neither a publication ledger nor proof of newest Freight or migration approval.

## Bounded work and activation

The selective job currently permits four channels, with two registry workers. Its action budget is 720 seconds and each channel's registry deadline is 300 seconds. Tree and policy fetching get 60 seconds, comparison gets 30 seconds, registry calls get 15 seconds and buffered command output is limited to 64 MiB. Selective copies get 120 seconds and readback gets 30 seconds. `COPY_TIMEOUT_SECONDS` and `READBACK_TIMEOUT_SECONDS` extend the shared helper; both default to 40 seconds for the unchanged common caller. The selective step gets 13 minutes and its job gets 18 minutes, including checkout, tag history and client setup.

These bounds combine retained history/matcher capacity with the local interval and four-channel measurement. They bound work and fail closed; they do not promise production upload-fallback throughput. Check ordinary publication latency and source-replica arrival during activation. A missing tree, failed bounded fetch or timeout never means unrelated input and never advances a blocked channel. A larger fan-out or longer quiet interval requires reviewed capacity and budget changes.

Channels remain empty until activation review. Before adding the first channel, bind its owner-reviewed complete filter, infrastructure-approved repositories and replicas, immutable tags, shared publisher permissions, local source replica, supported retention and rollback bounds, one seed and its fingerprint where needed. Verify applied IAM, encryption, mount and replication settings through the normal infrastructure rollout. During attended activation, check exact destination/replica digest agreement, consumer pulls, matching Freight and the approved first-promotion identity. Keep affected Stage holds until that evidence is accepted. This guidance grants no registry publication, infrastructure apply, cluster operation or rollout authority.
