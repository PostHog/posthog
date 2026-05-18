Hi Ilkhom,

Thank you for the detailed feedback! This helps clarify the scope.

The current PR (#58694) implements the basic "include all schemas" toggle - it discovers tables from all non-system schemas. However, the consolidation feature (merging tables from multiple schemas into master tables) would be a larger implementation.

To summarize what's done vs. what's needed:

**✅ Implemented:**
- "Include all schemas" toggle to discover tables from all schemas
- Users can query individual schema tables

**🔄 Could be added:**
- Schema selector to pick specific schemas (instead of all)
- Dynamic union-all across schemas at query time (views)

**❄️ More complex (future):**
- Table consolidation during sync (merge tables with same name into master tables)

The consolidation during sync could indeed be performance-intensive as you mentioned - it would need to read and merge data before saving to PostHog.

Would you like us to:
1. Extend the current PR to add schema selection (pick specific schemas instead of all)?
2. Keep the PR as-is for now and file separate issues for the consolidation features?

Let us know how you'd like to proceed!