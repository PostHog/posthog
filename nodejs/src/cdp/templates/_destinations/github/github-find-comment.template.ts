import { MAX_ASYNC_STEPS } from '~/cdp/services/hog-executor.service'
import { HogFunctionTemplate } from '~/cdp/types'

import { githubHogHelpers, githubIssueInputs } from './github-helpers'

const COMMENTS_PER_PAGE = 100
const PAGE_BUDGET = MAX_ASYNC_STEPS

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-github-find-comment',
    name: 'Find GitHub comment',
    description: 'Check if a GitHub issue or pull request has a comment that contains some text',
    icon_url: '/static/services/github.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${githubHogHelpers}

let repoPath := githubRepoPath(inputs.github_installation, inputs.repository)
let issueNumber := githubIssueNumber(inputs.number)

if (empty(inputs.text)) {
  throw Error('Comment text is required')
}

for (let page := 1; page <= ${PAGE_BUDGET}; page := page + 1) {
  let res := fetch(f'https://api.github.com/repos/{repoPath}/issues/{issueNumber}/comments?per_page=${COMMENTS_PER_PAGE}&page={page}', {
    'method': 'GET',
    'headers': githubHeaders(inputs.github_installation)
  })

  if (res.status < 200 or res.status >= 300) {
    throw Error(f'Failed to find GitHub comment ({res.status}): {githubErrorMessage(res)}')
  }
  if (typeof(res.body) != 'array') {
    throw Error(f'Failed to find GitHub comment ({res.status}): GitHub returned no comment list')
  }

  for (let comment in res.body) {
    if (typeof(comment.body) != 'string') {
      throw Error(f'Failed to find GitHub comment ({res.status}): GitHub returned a comment without a body')
    }
    if (position(comment.body, inputs.text) > 0) {
      return {'found': true, 'comment_id': comment.id, 'html_url': comment.html_url}
    }
  }

  if (length(res.body) < ${COMMENTS_PER_PAGE}) {
    return {'found': false, 'comment_id': null, 'html_url': null}
  }
}

throw Error('Searched the first ${PAGE_BUDGET * COMMENTS_PER_PAGE} comments and found no match. The issue or PR has more comments than this step can search.')
`,
    inputs_schema: [
        ...githubIssueInputs,
        {
            key: 'text',
            type: 'string',
            label: 'Comment text',
            description: 'Finds the first comment that contains this text. The match is case-sensitive.',
            secret: false,
            required: true,
        },
    ],
}
