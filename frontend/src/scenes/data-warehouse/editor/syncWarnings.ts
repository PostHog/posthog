// The backend `message` on a DataWarehouseSyncWarning is kept self-contained (it also feeds
// LLM/MCP contexts), so it restates "results may be out of date" — which the sync-warning banner
// header already says. Strip that redundant tail for display only, while preserving any
// "a new sync is in progress" detail. Messages without that tail (failed, paused) are left as-is.
export const trimRedundantTail = (message: string): string =>
    message
        .replace(/\.\s*(A new sync is in progress) but results may be out of date\.?\s*$/i, '. $1.')
        .replace(/\.\s*Results may be out of date\.?\s*$/i, '.')
