# Customer analytics email matching

Customer analytics uses a shared matcher to link email threads and calendar meetings to accounts.
The matcher checks each participant address in this order:

1. The account's `known_emails` property.
2. The person's associated group.
3. Organization membership, when the Gmail owner's staff-only account member search is enabled.
4. The account's `email_domains` property.

An ambiguous match stops further matching for that address.
Other participants can still match accounts.

## Internal email exclusion

The matcher removes addresses with the exact `@posthog.com` suffix before any matching step.
It trims whitespace and converts addresses to lowercase before this check.
This keeps internal participants from linking customer correspondence to internal accounts.
Subdomains and similar domain names do not match this exclusion.
Other participant addresses keep their existing matching behavior.

This rule uses `POSTHOG_INTERNAL_EMAIL_SUFFIX`.
It does not depend on account names or the `exclude_from_crm` group property.

## Existing links

The exclusion applies when the matcher processes new or updated email threads and calendar meetings.
Deployment alone does not change stored associations.

To update existing email links, call `schedule_email_thread_link_recalculation(team_id)` from `products.customer_analytics.backend.facade.email_matching` for the affected project after deployment.
The task replaces each thread's account links, including removing links that no longer match.
It preserves the email thread and its messages.
Check that customer links remain and excluded addresses no longer produce account links.

The calendar rematch task processes only meetings without an account.
It does not remove existing meeting assignments.
