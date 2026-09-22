# Customer analytics email matching

The shared matcher checks each participant address in this order:

1. The account's `known_emails` property.
2. The account's `email_domains` property.
3. The person's associated group.
4. Organization membership, when the Gmail owner's staff-only account member search is enabled.

A known email overrides a domain assignment.
A unique domain assignment takes priority over person groups and organization membership, including ambiguous results from those later sources.
Direct email matching and calendar matching skip organization membership.

The first match wins for each address.
No match allows the next step.
An ambiguous result stops matching for that address.
For example, if two accounts claim a domain, the matcher does not use a person group to choose between them.
Use `known_emails` to assign individual addresses on shared domains.

## Matching flow

This flow runs independently for each participant address.
Skip person-group matching when no account group type is configured.
Skip organization membership unless one active Gmail owner passes the staff and feature-flag checks.

```mermaid
flowchart TD
    Input[Participant email] --> Normalize[Trim whitespace and lowercase]
    Normalize --> Eligible{"Contains @ and is not<br/>an @posthog.com address?"}
    Eligible -->|No| Unmatched[No account match]
    Eligible -->|Yes| Stage["Try the next enabled stage<br/>1. Known email<br/>2. Email domain<br/>3. Person's group<br/>4. Organization membership"]
    Stage --> Result{Stage result?}
    Result -->|One account| Matched[Keep the match and stop]
    Result -->|Ambiguous| Unmatched
    Result -->|No match| More{More enabled stages?}
    More -->|Yes| Stage
    More -->|No| Unmatched

    classDef phBlue fill:#1d4aff,stroke:#1d4aff,color:#fff;
    classDef phYellow fill:#f9bd2b,stroke:#f9bd2b,color:#000;
    classDef phGray fill:#e5e7eb,stroke:#c7ccd1,color:#000;
    class Input,Matched,Unmatched phYellow;
    class Normalize,Stage phBlue;
    class Eligible,Result,More phGray;
```

Ambiguity stops all later stages for that address.
A lookup error can fail the task instead of allowing fallback.

## Thread links

Each participant can match a different account.
When several participants match the same account, the thread keeps one link with the highest-priority source from the order above.
A recalculation replaces the thread's account links and removes stale links without deleting messages.

Deployment alone does not recalculate existing links.
After deployment, use `schedule_email_thread_link_recalculation(team_id)` from `products.customer_analytics.backend.facade.email_matching` to update an affected project.
Check that a unique domain assignment wins over a competing group or membership match, while a known email still overrides the domain.
Calendar rematching processes only meetings without an account; it does not replace existing assignments.

## Unchanged safeguards

Addresses are trimmed and lowercased before matching.
The exact `@posthog.com` suffix is excluded before all steps.
The person-group lookup uses the project's configured account group type.
The organization-membership step keeps its existing Gmail-owner gate and local-region lookup; it does not query EU membership data from the US.
