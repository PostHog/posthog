---
name: extending-hobby-smoke-tests
description: Design, extend, review, or debug PostHog Hobby end-to-end smoke tests in bin/hobby-ci.py and .github/workflows/ci-hobby.yml. Use when adding an ingestion round trip, deciding whether a product belongs in Hobby CI, changing the CI Hobby service topology or API-key scopes, or diagnosing a smoke test that captures data but cannot query it.
---

# Extending Hobby smoke tests

Treat Hobby CI as proof that a supported Hobby install works across real process boundaries. Keep each check small, strong, and limited to a stable product surface.

## Decide whether the check belongs

Add a check only when all of these are true:

- The product is supported for Hobby deployments and is no longer alpha.
- A break can leave the install apparently healthy while the product is unusable.
- The check crosses boundaries that unit or service integration tests cannot cover, such as capture, queue, consumer, storage, and query API.
- The released Hobby images and default compose topology contain every required service.
- A deterministic request and an exact read-back assertion are available.

Do not add the check when it requires a private feature flag, a CI-only service topology, or a different image registry only to make an alpha path available. Test that path at a lower layer until it becomes part of the supported Hobby install.

If the check exposes a missing service or configuration that every supported Hobby install needs, fix the install and add the check together. If the missing plumbing exists only for the proposed test, stop and reconsider the check.

## Map the round trip before editing

Write down this chain from repository evidence:

```text
public ingest endpoint -> request contract -> service/consumer -> storage -> read API -> required scope
```

Verify each link:

1. Find an existing end-to-end or receiver fixture for the ingest payload. Reuse its envelope and minimum valid data instead of inventing a plausible payload.
2. Locate the consumer command and confirm it exists in the released image used by `docker-compose.hobby.yml`.
3. Confirm the consumer is already started by the default Hobby compose files.
4. Confirm no unreleased or private feature flag is required.
5. Find the supported read API and its personal API-key scope.
6. Identify a unique value that can select only the captured object.

Do this before starting a full Hobby run. A successful HTTP capture response proves receipt, not ingestion.

## Build the smallest strong check

Change `bin/hobby-ci.py` for the round trip and `bin/hobby-ci-setup-user.py` only for the least read scope needed.

- Generate collision-resistant identifiers with UUIDs or nanosecond timestamps.
- Record the query window before capture.
- Send the smallest payload known to reach storage.
- Fail immediately on a non-success capture response and include a short response body.
- Poll the supported read API with the exact identifier.
- Require the expected stored object or value. An HTTP 200 with an empty result is not success.
- Use the existing bounded timeout and polling style.
- Preserve earlier smoke checks and return a result that names every completed round trip.
- Keep one product idea per PR when the checks can fail independently.

Avoid adding general abstractions for a single payload. Extract a helper only when it removes real repetition or gives a concept a useful name.

## Validate from cheap to expensive

Run focused checks before asking Hobby CI to create a server:

```bash
python3 -m py_compile bin/hobby-ci.py bin/hobby-ci-setup-user.py
ruff check bin/hobby-ci.py bin/hobby-ci-setup-user.py
ruff format --check bin/hobby-ci.py bin/hobby-ci-setup-user.py
git diff --check
```

When compose or installer files change, also render the final compose configuration and run the focused installer tests. Inspect the rendered image and command for every added service.

Use a PR-specific image only when the PR changes code that must be built into that image. Do not change workflow path filters or registries merely because a smoke-test-only PR needs an unreleased service.

Then run Hobby CI once and follow the exact run through image build, cloud setup, health, and ingestion. Do not restart a healthy migration phase just because it is slow.

## Read failures by boundary

Use the first failed boundary to choose the next investigation:

| Evidence                                  | Likely boundary                                              |
| ----------------------------------------- | ------------------------------------------------------------ |
| Capture returns 4xx                       | Endpoint, token, or payload envelope                         |
| Read API returns 401 or 403               | Personal key scope or feature access                         |
| Capture succeeds, exact query stays empty | Payload semantics, missing consumer, routing, or storage     |
| Added container is absent or unhealthy    | Released image or default compose topology                   |
| Query returns 200 with empty series       | Not success; keep polling or strengthen the assertion        |
| Earlier product checks fail too           | Shared install or trunk failure, not the new assertion alone |

Pull the failed job log before editing. Confirm the hypothesis against the receiver fixture, consumer registration, compose rendering, and API implementation. Do not run another full deployment on a guessed payload.

## Review the final diff

Before publishing, prove the PR contains only what the supported round trip requires:

- No alpha-only feature flags.
- No registry or image-build changes unless product code in the PR requires a new image.
- No new service unless that service belongs in every supported Hobby install.
- No broad API scope.
- No assertion that accepts an empty response.
- No synthetic payload that lacks a known accepted fixture.

Update the PR description with the exact ingest and read-back proof. State any product intentionally excluded because it is not yet stable.
