# Warm-run submission

The web task composer keeps a submission pending while its warm run starts. It retains the draft and
unsent context, prevents duplicate submissions, and clears them only after the API confirms success.
If startup does not recover, it displays an error and leaves the message available to submit again.

Task creation and run resumption attempt Temporal message delivery once per API request, with a
10-second RPC timeout. A `NOT_FOUND` response proves nondelivery. If the same run and workflow are
still eligible, the API returns `503` with `code: warm_run_activation_unavailable` and a `retry_token`.
The signed token binds the run, workflow, and message ID and expires after 60 seconds.

Web repeats the identical request with the first token in `X-PostHog-Warm-Retry`. It waits 250 ms,
then 500 ms, then 1 second between attempts. The 20-second budget includes the initial request;
deadline handling begins only after a retryable startup response, leaving ordinary cold-start
requests unaffected. Requests stay sequential, and the budget continues while the tab is hidden.

Only the startup error with a nonempty token permits another attempt. Network failures, RPC timeouts,
and other ambiguous errors do not: delivery may already have occurred. An expired or invalid token,
or a cancelled, deleted, or changed target, cannot select a replacement run. Attached artifacts remain
available to retries of the same submission.

Disposing the owning logic cancels pending requests and backoff timers. Deadline expiry aborts the
pending request; late responses cannot complete the submission in the UI. Aborting HTTP does not undo
server-side delivery, so ambiguous failures need an explicit user retry.

Successful API responses retain their existing status codes and shapes. The retry header and token
are optional. Desktop and older clients can handle the response as an ordinary failed request;
automatic recovery requires client retry support. Deploy the backend before the web retry loop.
