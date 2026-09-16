# Replay Vision evaluation evidence

Successful scanner quality evaluations retain every structured finding in `signals`, alongside `signals_count`.
An empty result retains `signals: []`.
The output preserves each finding's type, time range, URL, description, and confidence for review against the recording.

Primary verdict agreement, signal counts, and model confidence do not measure recommendation precision.
The suite does not score each finding's evidence or usefulness.
Review the findings against the recording before using them to assess recommendations.

Signal payloads can contain session content.
Keep them private and out of public CI summaries, commits, and pull requests.
See the [evaluation README](../../products/replay_vision/evals/README.md) for run instructions and data handling restrictions.
