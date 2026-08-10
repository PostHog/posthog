import {COMPARE_FILE_LIMIT, getPushDeltaRange, isComparisonTruncated, PushDeltaPayload} from '../src/push-delta'

const BEFORE = '1111111111111111111111111111111111111111'
const AFTER = '2222222222222222222222222222222222222222'
const NULL_SHA = '0000000000000000000000000000000000000000'

describe('detecting changes from the last push only', () => {
  test('uses the pushed range on a synchronize event', () => {
    const range = getPushDeltaRange('pull_request', {action: 'synchronize', before: BEFORE, after: AFTER})
    expect(range).toEqual({usable: true, before: BEFORE, after: AFTER})
  })

  test.each<[string, string, PushDeltaPayload]>([
    ['a push to a branch', 'push', {before: BEFORE, after: AFTER}],
    ['a newly opened pull request', 'pull_request', {action: 'opened'}],
    ['a pull request leaving draft', 'pull_request', {action: 'ready_for_review'}],
    ['a payload without before', 'pull_request', {action: 'synchronize', after: AFTER}],
    ['a payload without after', 'pull_request', {action: 'synchronize', before: BEFORE}],
    ['a branch created at the null SHA', 'pull_request', {action: 'synchronize', before: NULL_SHA, after: AFTER}],
    ['a branch deleted to the null SHA', 'pull_request', {action: 'synchronize', before: BEFORE, after: NULL_SHA}],
    ['a push that did not move the head', 'pull_request', {action: 'synchronize', before: BEFORE, after: BEFORE}]
  ])('falls back to the full diff for %s', (_description, eventName, payload) => {
    expect(getPushDeltaRange(eventName, payload).usable).toBe(false)
  })

  test.each([
    ['an empty comparison', 0, false],
    ['a comparison below the cap', COMPARE_FILE_LIMIT - 1, false],
    ['a comparison at the cap', COMPARE_FILE_LIMIT, true],
    ['a comparison past the cap', COMPARE_FILE_LIMIT + 1, true]
  ])('decides whether %s is truncated', (_description, count, expected) => {
    expect(isComparisonTruncated(new Array(count).fill({}))).toBe(expected)
  })

  test('treats a comparison with no file list as truncated', () => {
    expect(isComparisonTruncated(undefined)).toBe(true)
  })
})
