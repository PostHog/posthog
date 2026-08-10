// The compare API caps its file list at 300 entries and does not paginate them,
// so a list at the cap may be truncated. Under-reporting changed files would let
// a workflow skip jobs it should have run, so the caller falls back to the full
// pull request diff instead.
export const COMPARE_FILE_LIMIT = 300

const NULL_SHA = '0000000000000000000000000000000000000000'

export interface PushDeltaPayload {
  action?: string
  before?: string
  after?: string
}

export type PushDeltaRange = {usable: true; before: string; after: string} | {usable: false; reason: string}

export function getPushDeltaRange(eventName: string, payload: PushDeltaPayload): PushDeltaRange {
  // Only a synchronize payload carries before/after. Every other pull request
  // action (opened, reopened, ready_for_review) has no previous head to compare
  // against, and those are exactly the events where the whole diff is wanted.
  if (eventName !== 'pull_request') {
    return {usable: false, reason: `event is ${eventName}, not pull_request`}
  }
  if (payload.action !== 'synchronize') {
    return {usable: false, reason: `pull request action is ${payload.action}, not synchronize`}
  }

  const {before, after} = payload
  if (!before || !after) {
    return {usable: false, reason: 'payload is missing before or after'}
  }
  if (before === NULL_SHA || after === NULL_SHA) {
    return {usable: false, reason: 'before or after is the null SHA'}
  }
  if (before === after) {
    return {usable: false, reason: 'before and after are the same commit'}
  }

  return {usable: true, before, after}
}

export function isComparisonTruncated(files: unknown[] | undefined): boolean {
  return files === undefined || files.length >= COMPARE_FILE_LIMIT
}
