# Account links

Customer analytics supports two account URL forms within the current project:

- `/customer_analytics/accounts/:accountId` identifies an account by its internal UUID.
- `/customer_analytics/accounts/by-external-id/:externalId` identifies an account by its exact external ID.

Both URLs open the same account detail scene when `customer-analytics-account-scene` is enabled.
Append a tab name, such as `/usage`, to open that tab.
Tab changes preserve the identifier form, query parameters, and URL hash.
Existing internal links continue to use the account UUID.

## External ID encoding

Use `urls.customerAnalyticsAccountByExternalId(externalId, tab)` to build external-ID links.
The helper encodes the external ID as one URL segment.
For example, the external ID `example/account` becomes `example%2Faccount` in the path.
Case and spaces are significant.

The route uses a local wildcard because the router's named parameters do not accept all external-ID characters.
The scene reads the raw path and decodes the external ID once.
An encoded slash remains part of the ID, rather than a tab separator.
A literal percent sequence must remain distinct from the character it could encode.

Accounts with no external ID require a UUID link.
Use UUID links for empty external IDs and IDs equal to `.` or `..`; browsers can normalize dot-only path segments before routing.

## API lookup

The external route loads the account through:

```text
GET /api/projects/:projectId/accounts/by_external_id/?external_id=...
```

The API accepts a required, nonempty string of at most 400 characters.
Use URL query encoding for this value, not path encoding.
The generated `accountsByExternalIdRetrieve` client handles query encoding.
The API preserves case and whitespace and matches only `external_id` within the project.
It does not fall back to the account UUID, even when the external ID is a UUID string.

The endpoint returns the same account response as UUID retrieval, including tags and notebooks.
It uses the same access controls and requires `account:read` for API credentials.
Invalid input returns 400, a missing account returns 404, and object-level access denial follows the existing 403 behavior.

## Scene behavior

The external route makes one account lookup request and keeps the result in the existing scene logic.
It does not resolve a UUID and then request the same account again.
Related panels still make their own requests.
Presence, tag edits, and nested account APIs use the returned `account.id`, never the external ID.
Presence starts after external-ID resolution succeeds.

The scene keeps external-ID links unchanged while the detail scene is enabled.
With the detail-scene flag disabled, a successful lookup redirects to the existing UUID route for the legacy Accounts view.
Loading failures retain the existing retry and not-found states.
