# Query coalescing

Cached query responses run authentication and permission checks before returning a shared result.
Their dispatch path also restores the team scope that was active before the request.

Place `TeamAndOrgViewSetMixin` before `QueryCoalescingMixin` in a viewset's base classes.
This lets the team-scope cleanup wrapper surround cached responses, which return without calling the next dispatch method.
The same order applies to query, insight, and account-table query viewsets.
