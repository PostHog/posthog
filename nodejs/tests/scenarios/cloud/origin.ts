import { execFileSync } from 'child_process'

import { internalFetch } from '~/common/utils/request'

import { Origin } from './admission'

const REPOSITORY = 'PostHog/posthog'
const REQUEST_TIMEOUT_MS = 10_000

export function githubOrigin(api: string = 'https://api.github.com'): Origin {
    return {
        head: () => execFileSync('git', ['rev-parse', 'HEAD'], { cwd: __dirname, encoding: 'utf8' }).trim(),
        published: async (commit) => {
            const response = await internalFetch(`${api}/repos/${REPOSITORY}/commits/${commit}`, {
                headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'posthog-scenario-runner' },
                timeoutMs: REQUEST_TIMEOUT_MS,
            })
            if (response.status === 404 || response.status === 422) {
                return false
            }
            if (response.status !== 200) {
                throw new Error(`GitHub answered ${response.status} for commit ${commit}`)
            }
            return true
        },
    }
}
