# Support mail is a platform route on the one Workflows intake, before its filters and storage

Workflows runs one SES intake that covers SES receipt, S3, SNS and MIME parsing. Our support inbound domains are a platform route on it, not a team `InboundEmailDomain`. The route hands parsed mail and SNS-signed verdicts to Conversations' existing ingest before Workflows' auto-submitted filter. It skips `ReceivedEmail` rows, `$email_received` and 30-day retention.

Two reasons for the early hand-off. Workflows stamps `Auto-Submitted: auto-generated` on its own sends, so the forwarding challenge would otherwise be filtered out. And support mail must not be stored twice.

Ownership: Dan Marchuk builds this from his closed SES stack, Conversations reviews the route and the adapter, and Workflows owns the inbound layer afterwards. Relay, DMARC-rewrite, challenge and autoreply policy stay in Conversations' ingest.

The adapter into Conversations' `ParsedEmail` lives at Conversations' edge, co-owned by Workflows, so Workflows never imports Conversations. Rejected: a second intake only for support, and Conversations parsing raw bytes itself, which would duplicate the bounded parser.
