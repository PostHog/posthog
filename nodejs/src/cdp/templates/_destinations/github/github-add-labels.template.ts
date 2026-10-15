import { HogFunctionTemplate } from '~/cdp/types'

import { githubHogHelpers, githubIssueInputs } from './github-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-github-add-labels',
    name: 'Add GitHub labels',
    description: 'Add labels to a GitHub issue or pull request',
    icon_url: '/static/services/github.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${githubHogHelpers}

let repoPath := githubRepoPath(inputs.github_installation, inputs.repository)
let issueNumber := githubIssueNumber(inputs.number)
let labels := githubSplitList(inputs.labels)

if (empty(labels)) {
  throw Error('Enter at least one label name')
}

let res := fetch(f'https://api.github.com/repos/{repoPath}/issues/{issueNumber}/labels', {
  'method': 'POST',
  'headers': githubJsonHeaders(inputs.github_installation),
  'body': {'labels': labels}
})

if (res.status < 200 or res.status >= 300) {
  throw Error(f'Failed to add GitHub labels ({res.status}): {githubErrorMessage(res)}')
}

if (typeof(res.body) != 'array') {
  throw Error(f'Failed to add GitHub labels ({res.status}): GitHub returned no label list')
}

let names := []
for (let item in res.body) {
  if (typeof(item.name) != 'string') {
    throw Error(f'Failed to add GitHub labels ({res.status}): GitHub returned a label without a name')
  }
  names := arrayPushBack(names, item.name)
}

return {'labels': names}
`,
    inputs_schema: [
        ...githubIssueInputs,
        {
            key: 'labels',
            type: 'string',
            label: 'Labels',
            description: 'Comma-separated label names',
            secret: false,
            required: true,
        },
    ],
}
