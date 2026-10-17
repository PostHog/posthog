import { HogFunctionTemplate } from '~/cdp/types'

import { githubHogHelpers, githubIssueInputs } from './github-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-github-remove-label',
    name: 'Remove GitHub label',
    description: 'Remove a label from a GitHub issue or pull request',
    icon_url: '/static/services/github.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${githubHogHelpers}

let repoPath := githubRepoPath(inputs.github_installation, inputs.repository)
let issueNumber := githubIssueNumber(inputs.number)
let label := githubTrimWhitespace(inputs.label)

if (empty(label)) {
  throw Error('Enter a label name')
}
if (label == '.' or label == '..') {
  throw Error('A label name cannot be . or ..')
}

let res := fetch(f'https://api.github.com/repos/{repoPath}/issues/{issueNumber}/labels/{encodeURLComponent(label)}', {
  'method': 'DELETE',
  'headers': githubHeaders(inputs.github_installation)
})

if (res.status == 404 and res.body.message == 'Label does not exist') {
  return {'removed': false}
}

if (res.status < 200 or res.status >= 300) {
  throw Error(f'Failed to remove GitHub label ({res.status}): {githubErrorMessage(res)}')
}

return {'removed': true}
`,
    inputs_schema: [
        ...githubIssueInputs,
        {
            key: 'label',
            type: 'string',
            label: 'Label',
            secret: false,
            required: true,
        },
    ],
}
