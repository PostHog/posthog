import { urls } from 'scenes/urls'

import type { TracePullRequestApi } from '../../../generated/api.schemas'
import { GitPullRequestLink } from '../types'

export function toGitPullRequestLink(pullRequest: TracePullRequestApi): GitPullRequestLink {
    return {
        number: pullRequest.number,
        title: pullRequest.title,
        href: urls.engineeringAnalyticsPullRequest(pullRequest.repoOwner, pullRequest.repoName, pullRequest.number),
    }
}
