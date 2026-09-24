# Streaming transcripts

Pi text and thought chunks publish together at most once per 16 ms batch.
Tool, queue, error, and completion events flush preceding text before they apply, preserving transcript order.
Disconnect cancels pending batches, and source ID indexes reject duplicate delivery without scanning the transcript for each chunk.

Pi and ACP use the same incremental transcript builder.
Completed rows retain their identity while the active turn streams.
Pi history revisions invalidate the builder when hydration or an optimistic acknowledgement changes an earlier message.
The chat footer consumes the body's derived state instead of parsing the same transcript again.

Cloud follow-up messages keep their submission ID until the agent prompt confirms delivery.
A confirmed delivery failure appears at the original send time with a Resend action that creates a new message.
While delivery is uncertain, the chat shows no failure marker.
Messages with missing attachments or shortened stored text cannot be resent from the failed-message row.

Verification:

- Deliver a burst of chunks and check that one transcript publication contains each source ID once.
- Complete or disconnect during a pending batch and check ordering and cleanup.
- Compare incremental output with a full build at every prefix, including late events and tool updates.
- Replace an optimistic message inside a consumed prefix and check that the confirmed content appears.
