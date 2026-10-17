import { HogFunctionTemplate } from '~/cdp/types'

import { githubHogHelpers, githubPullRequestInputs } from './github-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-github-get-pull-request',
    name: 'Get GitHub pull request',
    description: "Fetch a GitHub pull request's state, branches, and labels",
    icon_url: '/static/services/github.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${githubHogHelpers}

let repoPath := githubRepoPath(inputs.github_installation, inputs.repository)
let pullNumber := githubIssueNumber(inputs.number)

let res := fetch(f'https://api.github.com/repos/{repoPath}/pulls/{pullNumber}', {
  'method': 'GET',
  'headers': githubHeaders(inputs.github_installation)
})

if (res.status < 200 or res.status >= 300) {
  throw Error(f'Failed to get GitHub pull request ({res.status}): {githubErrorMessage(res)}')
}

let pr := res.body
return {
  'number': pr.number,
  'title': pr.title,
  'state': pr.state,
  'draft': pr.draft,
  'merged': pr.merged,
  'author': pr.user.login,
  'head_ref': pr.head.ref,
  'head_sha': pr.head.sha,
  'base_ref': pr.base.ref,
  'html_url': pr.html_url,
  'labels': arrayMap(label -> label.name, pr.labels)
}
`,
    inputs_schema: githubPullRequestInputs,
}
