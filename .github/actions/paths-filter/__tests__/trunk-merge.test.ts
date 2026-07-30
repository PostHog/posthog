import {parseTestedPrNumbers, trunkMergeLeadPr} from '../src/trunk-merge'

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
    ['batch of two, dependencies excluded', BATCH_BODY, [74757, 73853]],
    ['single PR (bisection)', SINGLE_PR_BODY, [73792]],
    ['batch body with CRLF line endings', BATCH_BODY.replace(/\n/g, '\r\n'), [74757, 73853]],
    ['missing tested section', 'This PR depends on [1](https://www.github.com/PostHog/posthog/pull/1).', []],
    ['empty body', '', []],
    [
      'foreign repos and lookalike hosts ignored',
      `## Pull Requests Being Tested

Testing [111](https://www.github.com/PostHog/posthog/pull/111), [999](https://www.github.com/OtherOrg/other-repo/pull/999), [9](https://github.com.evil.io/PostHog/posthog/pull/9) and [7](https://notgithub.com/PostHog/posthog/pull/7).
`,
      [111]
    ],
    [
      'repeated links deduplicated',
      `## Pull Requests Being Tested

[42](https://www.github.com/PostHog/posthog/pull/42) and again [42](https://www.github.com/PostHog/posthog/pull/42).
`,
      [42]
    ]
  ])('parseTestedPrNumbers: %s', (_name, body, expected) => {
    expect(parseTestedPrNumbers(body, REPO)).toEqual(expected)
  })

  test.each([
    ['trunk-merge/pr-74757/56ddd0d8-4bd4-4b4f-b61a-6899fc540034', 74757],
    ['trunk-merge/pr-73792/8eb3d9bb-07c3-44e0-8467-ae8c04a3511b-bisection', 73792],
    ['feature/trunk-merge-lookalike', null],
    ['trunk-merge/no-pr-number', null],
    [undefined, null]
  ])('trunkMergeLeadPr(%s) = %s', (ref, expected) => {
    expect(trunkMergeLeadPr(ref)).toBe(expected)
  })
})
