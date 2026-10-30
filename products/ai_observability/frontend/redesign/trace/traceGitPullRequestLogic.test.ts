import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceGitApi, TracePullRequestApi } from '../../generated/api.schemas'
import { decodeIdSegment, makeTraceResource } from './adapter/testFixtures'
import { traceGitPullRequestLogic } from './traceGitPullRequestLogic'
import { traceViewLogic } from './traceViewLogic'

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const PULL_REQUEST_URL = '/api/projects/:team_id/ai_observability/traces/:id/pull_request/'
const FLAG = FEATURE_FLAGS.ENGINEERING_ANALYTICS
const GIT: TraceGitApi = { branch: 'feat/rag', repo: 'acme/app' }
const PULL_REQUEST: TracePullRequestApi = {
    repoOwner: 'acme',
    repoName: 'app',
    number: 42,
    title: 'Answer billing questions',
}
const CREATED_AT = makeTraceResource().createdAt

describe('traceGitPullRequestLogic', () => {
    let requests: { traceId: string; timestampHint: string | null }[]
    let pullRequestStatus: number
    let traceBranch: TraceGitApi | null

    function setFlag(enabled: boolean): void {
        featureFlagLogic.actions.setFeatureFlags(enabled ? [FLAG] : [], { [FLAG]: enabled })
    }

    async function mountedLogic(git: TraceGitApi | null): Promise<ReturnType<typeof traceGitPullRequestLogic.build>> {
        traceBranch = git
        const props = { traceId: 'trace-1', timestampHint: null }
        const logic = traceGitPullRequestLogic(props)
        logic.mount()
        await expectLogic(traceViewLogic(props)).toDispatchActions(['loadTraceSuccess'])
        await expectLogic(logic).toFinishAllListeners()
        return logic
    }

    beforeEach(() => {
        requests = []
        pullRequestStatus = 200
        traceBranch = null
        useMocks({
            get: {
                [TRACE_URL]: () => [200, makeTraceResource({ git: traceBranch })],
                [EVALUATIONS_URL]: () => [200, { results: [] }],
                [PULL_REQUEST_URL]: ({ request, params }) => {
                    requests.push({
                        traceId: decodeIdSegment(String(params.id)),
                        timestampHint: new URL(request.url).searchParams.get('timestamp_hint'),
                    })
                    return pullRequestStatus === 200
                        ? [200, { pullRequest: PULL_REQUEST }]
                        : [pullRequestStatus, { detail: 'nope' }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        ['the flag is on and the trace has a branch', true, GIT, 1],
        ['the flag is off', false, GIT, 0],
        ['the trace has no branch', true, null, 0],
    ])('reads the pull request when %s', async (_description, flagOn, git, expectedRequests) => {
        setFlag(flagOn)

        const logic = await mountedLogic(git)

        expect(requests).toEqual(Array(expectedRequests).fill({ traceId: 'trace-1', timestampHint: CREATED_AT }))
        expect(logic.values.pullRequest).toEqual(expectedRequests ? PULL_REQUEST : null)
    })

    it('reads it once when the flags arrive after the trace', async () => {
        setFlag(false)
        const logic = await mountedLogic(GIT)

        setFlag(true)
        setFlag(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(requests).toHaveLength(1)
    })

    it('keeps the plain chip when the read fails', async () => {
        const toast = jest.spyOn(lemonToast, 'error')
        pullRequestStatus = 500
        setFlag(true)

        const logic = await mountedLogic(GIT)

        expect(requests).toHaveLength(1)
        expect(logic.values.pullRequest).toBeNull()
        expect(toast).not.toHaveBeenCalled()
    })
})
