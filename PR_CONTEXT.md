# Data Table Column Bug - Full Context

## Root Cause Timeline

### The Dormant Bug (2023)

- **PR #13873** (Jan 23, 2023) by @mariusandra
- Added check to handle loading states when switching query types
- Too aggressive: returned empty array whenever `columnsInQuery !== columnsInResponse`
- Remained dormant for 2+ years because condition rarely occurred

### The Trigger (2026)

- **PR #45611** (Jan 28, 2026) by @arthurdedeus
- Added table views feature which made the condition trigger constantly
- When applying views/adding columns:
  1. Query updates synchronously
  2. API request is asynchronous
  3. Brief mismatch period → old check returns `[]` → empty table

### The Fix (This PR)

- Remove unnecessary check from `dataTableLogic.ts`
- `DataTable.tsx` already handles column mismatches properly
- Add test to prevent regression
