import { execFileSync } from 'child_process'

import { internalFetch } from '~/common/utils/request'

import { Origin } from './admission'

const REPOSITORY = 'PostHog/posthog'
const REQUEST_TIMEOUT_MS = 10_000

export function githubOrigin(api: string = 'https://api.github.com', repo: string = __dirname): Origin {
    return {
        head: () => execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
        cardAt: (commit, id) =>
            execFileSync('git', ['show', `${commit}:nodejs/tests/scenarios/cards/${id}.yaml`], {
                cwd: repo,
                encoding: 'utf8',
                stdio: ['ignore', 'pipe', 'pipe'],
            }),
        onMaster: async (commit) => {
            const response = await internalFetch(`${api}/repos/${REPOSITORY}/compare/master...${commit}`, {
                headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'posthog-scenario-runner' },
                timeoutMs: REQUEST_TIMEOUT_MS,
            })
            if (response.status === 404 || response.status === 422) {
                return false
            }
            if (response.status !== 200) {
                throw new Error(`GitHub answered ${response.status} comparing commit ${commit} with master`)
            }
            const { status } = (await response.json()) as { status?: unknown }
            return status === 'identical' || status === 'behind'
        },
    }
}
