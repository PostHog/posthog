# Seed before processes start, head first

The lifecycle runs in this order:

1. build
2. stop, head first
3. reset, tail first
4. **seed, head first**
5. start, tail first
6. ready
7. drive
8. quiet
9. `validAfter`
10. judge

Seed writes rows and starts nothing. Each adapter receives the upstream adapters' exports, such as the cohort id the Workflows hook flow triggers on.

Seeding after start looks more natural, and it is what the first drafts did. But the cohort stream processor and the cohort event shuffler load their catalog and team index at boot, then refresh them only every 300 s plus jitter (`rust/cohort-stream-processor/src/config.rs`, `rust/cohort-event-shuffler/src/config.rs`). A cohort seeded after start would be missed until the next refresh. The trigger skips the backfill that follows (`cdp-cohort-membership-trigger.consumer.ts`), so every unit would read as lost.

Seeding before start puts the rows in place for the boot-time load. `ready` then confirms that the catalog covers the cohort.
