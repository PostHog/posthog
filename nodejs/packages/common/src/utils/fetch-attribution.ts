import { AsyncLocalStorage } from 'node:async_hooks'

// Caller attribution (e.g. teamId, hogFunctionId) for URL-validation check logs. The DNS
// check runs inside undici's connect flow, which has no caller context — callers that want
// attributed logs wrap their fetch in `fetchAttribution.run({...}, ...)`.
// Lives in its own module so tests that mock `./request` don't replace it with undefined.
export const fetchAttribution = new AsyncLocalStorage<Record<string, unknown>>()
