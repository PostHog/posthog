import {isTrunkMergeRef, parseTestedPrNumbers} from '../src/trunk-merge'

const REPO = {owner: 'PostHog', repo: 'posthog'}

// Condensed from real bodies Trunk authored on PostHog/posthog queue PRs.
const BATCH_BODY = `
This pull request was created and is being managed by [Trunk Merge](https://docs.trunk.io/merge-queue).

This pull request is based on the [master branch](https://github.com/PostHog/posthog/tree/master) at [SHA 088456d](https://github.com/PostHog/posthog/commit/088456d).

See more details about each PR in the batch here:
* [PR 74757](https://app.trunk.io/posthog-inc/merge-queue/3921a8a3/74757)
* [PR 73853](https://app.trunk.io/posthog-inc/merge-queue/3921a8a3/73853)

## Pull Requests Being Tested

This pull request is testing a batch with the changes from pull requests [74757](https://www.github.com/PostHog/posthog/pull/74757) and [73853](https://www.github.com/PostHog/posthog/pull/73853) - [batching documentation](https://docs.trunk.io/merge-queue/batching).

## Dependencies

This pull request depends on the changes from pull requests [74793](https://www.github.com/PostHog/posthog/pull/74793), [74914](https://www.github.com/PostHog/posthog/pull/74914), and [74763](https://www.github.com/PostHog/posthog/pull/74763).
`

const SINGLE_PR_BODY = `
## Pull Requests Being Tested

This pull request is testing the changes from pull request [73792](https://www.github.com/PostHog/posthog/pull/73792).

## Dependencies
`

describe('trunk-merge', () => {
  test.each([
    ['batch of two', BATCH_BODY, [74757, 73853]],
    ['single PR (bisection)', SINGLE_PR_BODY, [73792]],
    ['missing tested section', 'This PR depends on [1](https://www.github.com/PostHog/posthog/pull/1).', []],
    ['empty body', '', []]
  ])('parseTestedPrNumbers: %s', (_name, body, expected) => {
    expect(parseTestedPrNumbers(body, REPO)).toEqual(expected)
  })

  test('never returns numbers from the Dependencies section', () => {
    const tested = parseTestedPrNumbers(BATCH_BODY, REPO)
    for (const dependent of [74793, 74914, 74763]) {
      expect(tested).not.toContain(dependent)
    }
  })

  test('ignores PR links pointing at other repositories', () => {
    const body = `## Pull Requests Being Tested

Testing [111](https://www.github.com/PostHog/posthog/pull/111) and [999](https://www.github.com/OtherOrg/other-repo/pull/999).
`
    expect(parseTestedPrNumbers(body, REPO)).toEqual([111])
  })

  test('deduplicates repeated links', () => {
    const body = `## Pull Requests Being Tested

[42](https://www.github.com/PostHog/posthog/pull/42) and again [42](https://www.github.com/PostHog/posthog/pull/42).
`
    expect(parseTestedPrNumbers(body, REPO)).toEqual([42])
  })

  test.each([
    ['trunk-merge/pr-74757/56ddd0d8-4bd4-4b4f-b61a-6899fc540034', true],
    ['trunk-merge/pr-73792/8eb3d9bb-07c3-44e0-8467-ae8c04a3511b-bisection', true],
    ['feature/trunk-merge-lookalike', false],
    [undefined, false]
  ])('isTrunkMergeRef(%s) = %s', (ref, expected) => {
    expect(isTrunkMergeRef(ref)).toBe(expected)
  })
})
