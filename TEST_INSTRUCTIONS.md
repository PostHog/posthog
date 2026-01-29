# Testing Instructions for Data Table Column Fix

## Issue

When adding a column to a data table (e.g., on the activity page), the table would show no results even though the query API returns results.

## Root Cause

The `dataTableLogic.ts` had an overly aggressive check that returned an empty array when `columnsInQuery` didn't match `columnsInResponse`:

```typescript
// must be loading
if (!equal(columnsInQuery, columnsInResponse)) {
    return []
}
```

This check was meant to handle loading states, but it prevented showing results that were already available from the API.

## Fix

Removed the problematic check in `dataTableLogic.ts`. The `DataTable.tsx` component already handles column mismatches appropriately by using `columnsInResponse` when available.

## Manual Testing Steps

1. Navigate to any page with a data table that supports adding columns (e.g., Events page, Activity log, Persons list)
2. Ensure the table is showing results
3. Add a new column using the column configurator or the "Add column" option in the column dropdown
4. Verify that:
   - The table continues to show results (not empty)
   - The new column appears in the table
   - Data is displayed correctly in all columns

## Automated Testing

Added a new test case: `shows results even when columns in query do not match columns in response`

This test verifies that when columns are added (columnsInQuery !== columnsInResponse), the table still displays the available results instead of an empty array.

## Files Changed

- `frontend/src/queries/nodes/DataTable/dataTableLogic.ts` - Removed the problematic equality check
- `frontend/src/queries/nodes/DataTable/dataTableLogic.test.ts` - Added test case for the fix
