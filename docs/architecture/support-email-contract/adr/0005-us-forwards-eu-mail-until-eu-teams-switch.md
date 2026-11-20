# US receives the shared address and forwards EU mail until EU teams switch

One domain has one MX, and US and EU share one support inbound domain today. EU therefore gets its own inbound domain, received in Frankfurt, and new EU channels get it at once. Existing EU teams move their forwarding address in the same 8-week window as the sender DNS campaign.

Until they do, US SES receives the shared address. The US route answers ingress ownership from the recipient token, and ingress forwards the signed SNS body to EU, as it does for Mailgun today. EU reads the intake object from the US bucket and acks, so EU mail rests in US storage only in transit, the same as with Mailgun now.

Stack D deletes the forward, the ownership callback and the cross-account read once the window closes.
