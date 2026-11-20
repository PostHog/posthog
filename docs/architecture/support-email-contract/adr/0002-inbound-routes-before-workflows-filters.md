# Inbound mail reaches Conversations before Workflows' own filters and storage

Workflows owns SES receipt, S3, SNS and MIME parsing. It hands a Workflows-owned `InboundEmail` to a route that Conversations registers. It does this before its auto-submitted filter and before `ReceivedEmail`, `$email_received` and the 30-day retention. Conversations owns the adapter into its `ParsedEmail` and every policy: relay, DMARC rewrite, forwarding challenge and autoreply.

Two reasons for the early hand-off. Workflows stamps `Auto-Submitted: auto-generated` on its own sends, so the forwarding challenge would be filtered out. And support mail must not be stored twice. Two options were rejected: Conversations parsing raw bytes would duplicate the bounded parser, and Workflows building Conversations' type would point the dependency the wrong way.
