Hi Ilkhom,

Thanks for the detailed use case! Let me break this down:

**1. Schema selector (pick specific schemas)**
Yes, this can be added to the PR. Instead of just "include all schemas" toggle, we could add a field to enter specific schema names (comma-separated or multi-select).

**2. Dynamic union-all at query time**
PostHog's SQL editor allows running queries. You could write:
```sql
SELECT * FROM postgres Schema1.table
UNION ALL
SELECT * FROM postgres Schema2.table
UNION ALL
...
```
However, the "automatically union all tables with same name across schemas" would require additional work to generate this SQL dynamically.

**3. Master table consolidation**
Creating a consolidated `order_master` from 900+ schemas would be very resource-intensive during sync. It might be better to:
- Use the current PR to discover tables across all schemas
- Write a SQL view that dynamically unions across schemas at query time
- Or use dbt outside PostHog to create the master table before syncing

**Complexity:**
- Schema selector: Low complexity, can add to current PR
- Dynamic union generation: Medium complexity
- Pre-sync consolidation: High complexity (performance concerns)

**Timeline:** The current PR is in review. We can extend it with schema selection, but the full dynamic union-all feature would be a separate effort.

Would you like us to:
1. Extend current PR with schema selection (pick specific schemas)?
2. File a new issue for the dynamic union feature to be prioritized separately?

Thank you!