import { HogFunctionTemplate } from '~/cdp/types'

import { githubHogHelpers, githubPullRequestInputs } from './github-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-github-request-reviewers',
    name: 'Request GitHub reviewers',
    description: 'Request reviews from users or teams on a GitHub pull request',
    icon_url: '/static/services/github.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${githubHogHelpers}

let repoPath := githubRepoPath(inputs.github_installation, inputs.repository)
let pullNumber := githubIssueNumber(inputs.number)

let request := {}
let reviewers := githubSplitList(inputs.reviewers)
if (notEmpty(reviewers)) {
  request['reviewers'] := reviewers
}
let teamReviewers := githubSplitList(inputs.team_reviewers)
if (notEmpty(teamReviewers)) {
  request['team_reviewers'] := teamReviewers
}

if (empty(request)) {
  throw Error('Enter at least one reviewer or team')
}

let res := fetch(f'https://api.github.com/repos/{repoPath}/pulls/{pullNumber}/requested_reviewers', {
  'method': 'POST',
  'headers': githubJsonHeaders(inputs.github_installation),
  'body': request
})

if (res.status < 200 or res.status >= 300) {
  throw Error(f'Failed to request GitHub reviewers ({res.status}): {githubErrorMessage(res)}')
}

if (typeof(res.body.requested_reviewers) != 'array' or typeof(res.body.requested_teams) != 'array') {
  throw Error(f'Failed to request GitHub reviewers ({res.status}): GitHub returned no reviewer or team list')
}

return {
  'requested_reviewers': arrayMap(user -> user.login, res.body.requested_reviewers),
  'requested_teams': arrayMap(team -> team.slug, res.body.requested_teams)
}
`,
    inputs_schema: [
        ...githubPullRequestInputs,
        {
            key: 'reviewers',
            type: 'string',
            label: 'Reviewers',
            description: 'Comma-separated GitHub usernames',
            secret: false,
            required: false,
        },
        {
            key: 'team_reviewers',
            type: 'string',
            label: 'Team reviewers',
            description: 'Comma-separated team slugs',
            secret: false,
            required: false,
        },
    ],
}
