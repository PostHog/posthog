import { HogFunctionTemplate } from '~/cdp/types'

import { githubHogHelpers, githubIssueInputs } from './github-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-github-update-issue',
    name: 'Update GitHub issue or PR',
    description: 'Close, reopen, or edit the title or body of a GitHub issue or pull request',
    icon_url: '/static/services/github.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${githubHogHelpers}

let repoPath := githubRepoPath(inputs.github_installation, inputs.repository)
let issueNumber := githubIssueNumber(inputs.number)

let changes := {}
if (notEmpty(inputs.title)) {
  changes['title'] := inputs.title
}
if (notEmpty(inputs.body)) {
  changes['body'] := inputs.body
}
if (notEmpty(inputs.state)) {
  changes['state'] := inputs.state
}

if (empty(changes)) {
  throw Error('Set a title, body, or state to update')
}

let res := fetch(f'https://api.github.com/repos/{repoPath}/issues/{issueNumber}', {
  'method': 'PATCH',
  'headers': githubJsonHeaders(inputs.github_installation),
  'body': changes
})

if (res.status < 200 or res.status >= 300) {
  throw Error(f'Failed to update GitHub issue or PR ({res.status}): {githubErrorMessage(res)}')
}

return {'number': res.body.number, 'title': res.body.title, 'state': res.body.state, 'html_url': res.body.html_url}
`,
    inputs_schema: [
        ...githubIssueInputs,
        {
            key: 'title',
            type: 'string',
            label: 'Title',
            description: 'Leave empty to keep the current title.',
            secret: false,
            required: false,
        },
        {
            key: 'body',
            type: 'string',
            label: 'Body',
            description: 'Leave empty to keep the current body.',
            secret: false,
            required: false,
        },
        {
            key: 'state',
            type: 'choice',
            label: 'State',
            choices: [
                { label: 'Leave unchanged', value: '' },
                { label: 'Open', value: 'open' },
                { label: 'Closed', value: 'closed' },
            ],
            default: '',
            secret: false,
            required: false,
        },
    ],
}
