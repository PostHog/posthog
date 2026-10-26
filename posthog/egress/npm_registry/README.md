# npm registry egress

Anonymous reads of package metadata from the public npm registry at `https://registry.npmjs.org`.

## Identity

The constant scope `public`.
Requests carry no credential, so there is no account to budget per caller.

## Budget

None: calls are recorded, never gated (`RecordedEgressClient`).
The registry documents no numeric request limit.
npm's acceptable-use notice says the registry may block or rate-limit traffic that exceeds acceptable use, and asks clients to handle `429`.
Callers treat any non-`200` as a failed lookup.
Add a gate only if npm publishes a limit a budget can model.

## Lanes and callers

No lanes, because nothing is gated.
`products/stamphog/backend/logic/renovate_verification.py` is the caller.
It reads one full packument per package that a Renovate pull request changes, to check the version's publish time, tarball integrity, provenance attestation and install scripts.

## Rate-limit headers

None documented, so the domain declares no gauges.
The counter is `npm_registry_api_requests_total`, labeled `scope, method, endpoint, status_code, source`.
The `endpoint` label is a fixed name such as `packument`, never a package name.

## Auth

None.

## Sources

- [npm registry package metadata](https://github.com/npm/registry/blob/main/docs/responses/package-metadata.md): the full packument carries `time` (a map from version to publish time) and per-version `dist.integrity`; the full format omits `hasInstallScript`, so install scripts are read from the version's `scripts` object.
- [npm acceptable use (archived blog post)](https://blog.npmjs.org/post/187698412060/acceptible-use): the registry may block or rate-limit requests above acceptable use. Unverified: no numeric limit and no rate-limit header is documented.
- [Introducing npm package provenance](https://github.blog/security/supply-chain-security/introducing-npm-package-provenance/): provenance is published per version. The live packument shape `dist.attestations.provenance.predicateType` was read from `https://registry.npmjs.org/posthog-js` in October 2026.
