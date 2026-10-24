import { HogFunctionInputSchemaType } from '~/cdp/types'

// The request carries an installation token, so the repository and number must not be able to
// steer it to another API path.
export const githubHogHelpers = `fun githubRepoPath(installation, repository) {
  let path := repository
  if (notEmpty(repository) and position(repository, '/') == 0) {
    path := f'{installation.account.name}/{repository}'
  }
  if (not match(path, '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')) {
    throw Error('Repository must be a repository name or owner/repo')
  }
  for (let segment in splitByString('/', path)) {
    if (segment == '.' or segment == '..') {
      throw Error('Repository must be a repository name or owner/repo')
    }
  }
  return path
}

fun githubIssueNumber(value) {
  if (not match(toString(value), '^[1-9][0-9]*$')) {
    throw Error('Issue or PR number must be a positive whole number')
  }
  return toInt(value)
}

fun githubHeaders(installation) {
  return {
    'Authorization': f'Bearer {installation.access_token}',
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'PostHog Github App'
  }
}

fun githubJsonHeaders(installation) {
  let headers := githubHeaders(installation)
  headers['Content-Type'] := 'application/json'
  return headers
}

fun githubErrorMessage(response) {
  return response.body.message ?? response.body
}`

export const githubIssueInputs: HogFunctionInputSchemaType[] = [
    {
        key: 'github_installation',
        type: 'integration',
        integration: 'github',
        label: 'GitHub installation',
        secret: false,
        required: true,
    },
    {
        key: 'repository',
        type: 'string',
        label: 'Repository',
        description: 'Repository name, or owner/repo. With a GitHub trigger, this is the repository from the event.',
        secret: false,
        required: true,
        default: '{event.properties.repository}',
    },
    {
        key: 'number',
        type: 'string',
        label: 'Issue or PR number',
        description: 'With a GitHub trigger, this is the issue or pull request from the event.',
        secret: false,
        required: true,
        default: '{event.properties.number}',
    },
]
