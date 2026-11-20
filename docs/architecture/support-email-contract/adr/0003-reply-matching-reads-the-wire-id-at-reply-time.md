# Reply matching reads the SES wire Message-ID when a reply arrives

SES replaces the Message-ID that Conversations sets, so a customer's In-Reply-To names an ID only Workflows knows. When Conversations' own `EmailMessageMapping` misses, it asks Messaging `match_sent_message_ids`. That reads the SES message ID the CDP worker records on email status events in ClickHouse. Conversations then caches the hit as a mapping row.

The rejected option was an async job that writes wire IDs into Conversations after each send, which leaves a lag window and needs a second moving part. The accepted cost: status rows live 31 days, so a first reply to an agent-started thread after a month opens a new ticket.
