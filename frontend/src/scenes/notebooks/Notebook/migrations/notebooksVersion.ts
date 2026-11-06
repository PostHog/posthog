// NOTE: Increment this number when you add a new content migration to migrate.ts
// It will bust the cache on the localContent in the notebookLogic
// so that the latest content will fall back to the remote content which
// is filtered through the migrate function that ensures integrity
export const NOTEBOOKS_VERSION = '3'
