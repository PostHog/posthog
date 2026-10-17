import { HogFunctionTemplate } from '~/cdp/types'

import { githubHogHelpers, githubIssueInputs } from './github-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-github-add-assignees',
    name: 'Assign GitHub users',
    description: 'Assign users to a GitHub issue or pull request',
    icon_url: '/static/services/github.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${githubHogHelpers}

let repoPath := githubRepoPath(inputs.github_installation, inputs.repository)
let issueNumber := githubIssueNumber(inputs.number)
let assignees := githubSplitList(inputs.assignees)

if (empty(assignees)) {
  throw Error('Enter at least one GitHub username')
}

let res := fetch(f'https://api.github.com/repos/{repoPath}/issues/{issueNumber}/assignees', {
  'method': 'POST',
  'headers': githubJsonHeaders(inputs.github_installation),
  'body': {'assignees': assignees}
})

if (res.status < 200 or res.status >= 300) {
  throw Error(f'Failed to assign GitHub users ({res.status}): {githubErrorMessage(res)}')
}

if (typeof(res.body.assignees) != 'array') {
  throw Error(f'Failed to assign GitHub users ({res.status}): GitHub returned no assignee list')
}

return {'assignees': arrayMap(user -> user.login, res.body.assignees)}
`,
    inputs_schema: [
        ...githubIssueInputs,
        {
            key: 'assignees',
            type: 'string',
            label: 'Assignees',
            description: 'Comma-separated GitHub usernames',
            secret: false,
            required: true,
        },
    ],
}
