# PyPI egress

Anonymous reads of release metadata and provenance from `https://pypi.org`.

## Identity

The constant scope `public`.
Requests carry no credential, so there is no account to budget per caller.

## Budget

None: calls are recorded, never gated (`RecordedEgressClient`).
PyPI documents no request limit for the JSON API or the Integrity API.
The Integrity API documents `403` for when PyPI administrators disable access, and callers treat any status they do not expect as a failed lookup.
Add a gate only if PyPI publishes a limit a budget can model.

## Lanes and callers

No lanes, because nothing is gated.
`products/stamphog/backend/logic/renovate_verification.py` is the caller.
It reads the release JSON for each old and new version that a Renovate pull request changes, to check file hashes and upload times, and asks the Integrity API whether the old and new wheels carry provenance.

## Rate-limit headers

None documented, so the domain declares no gauges.
The counter is `pypi_api_requests_total`, labeled `scope, method, endpoint, status_code, source`.
The `endpoint` label is a fixed name such as `release` or `provenance`, never a project name.

## Auth

None.

## Sources

- [PyPI JSON API](https://docs.pypi.org/api/json/): `GET /pypi/<project>/<version>/json` lists the release files with their `digests` (`sha256` among them), `packagetype` and `upload_time_iso_8601`. Unverified: the page states no request limit and no rate-limit header.
- [PyPI Integrity API](https://docs.pypi.org/api/integrity/): `GET /integrity/<project>/<version>/<filename>/provenance` answers `404` when the file has no provenance and `403` when access is disabled by the administrators.
