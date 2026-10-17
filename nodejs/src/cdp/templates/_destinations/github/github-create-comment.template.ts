import { HogFunctionTemplate } from '~/cdp/types'

import { githubHogHelpers, githubIssueInputs } from './github-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-github-create-comment',
    name: 'Add GitHub comment',
    description: 'Post a comment on a GitHub issue or pull request',
    icon_url: '/static/services/github.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${githubHogHelpers}

let repoPath := githubRepoPath(inputs.github_installation, inputs.repository)
let issueNumber := githubIssueNumber(inputs.number)

if (empty(inputs.body)) {
  throw Error('Comment is required')
}

let res := fetch(f'https://api.github.com/repos/{repoPath}/issues/{issueNumber}/comments', {
  'method': 'POST',
  'headers': githubJsonHeaders(inputs.github_installation),
  'body': {'body': inputs.body}
})

if (res.status < 200 or res.status >= 300) {
  throw Error(f'Failed to add GitHub comment ({res.status}): {githubErrorMessage(res)}')
}

return {'comment_id': res.body.id, 'html_url': res.body.html_url}
`,
    inputs_schema: [
        ...githubIssueInputs,
        {
            key: 'body',
            type: 'string',
            label: 'Comment',
            secret: false,
            required: true,
        },
    ],
}
