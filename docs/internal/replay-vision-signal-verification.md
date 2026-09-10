# Replay Vision signal verification

The `verify_positives` scanner snapshot mode also controls candidate signal verification.
The default `off` mode and unknown values preserve existing behavior.
No production setting changes in this implementation.

In `shadow` mode, candidate assessment does not change the returned signals.
In `enforce` mode, only supported original candidates can be returned.
Each assessment must identify the candidate, match its URL, cite a time inside its interval, and include nonblank reasoning.
Duplicate or unknown candidate indexes reject the assessment response.
Missing, unsupported, or inconclusive assessments withhold the affected candidates.

The assessment uses a fresh conversation over the cached recording and event tools.
It checks the exact claim and visible material impact without the first pass reasoning or confidence.
It cannot replace a candidate with a different finding.
The check runs for signal-emitting scanners, not only monitors.

An enforced positive monitor must first pass its existing verdict verification.
If that check disagrees or cannot run, its signals are withheld.
The existing monitor result contract stays unchanged, including its original-verdict fallback on verification failure.
Missing cache, exhausted time budget, invalid assessment, timeout, or provider failure withholds signals in enforce mode.
These failures do not discard the main scanner result.

Model calls use the existing AI trace with the `verify_signals` span name.
Structured logs record mode, outcome, candidate count, and retained count without candidate content or provider error text.

Candidate agreement does not prove correctness or usefulness.
Before enabling enforcement, review private labeled recordings and measure supported, useful recommendations among those returned.
Treat a false positive in that review as a release blocker.
Do not use recall, model confidence, or agreement alone as the release criterion.
