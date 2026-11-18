import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../../generated/api'
import type { FeatureRequestApi } from '../../generated/api.schemas'
import { featureRequestGithubLogic } from './featureRequestGithubLogic'
import { featureRequestsLogic } from './featureRequestsLogic'

const request: FeatureRequestApi = {
    id: 'request-1',
    title: 'Export account-level retention data',
    description: 'The customer needs this for reporting.',
    request_status: 'planned',
    request_priority: null,
    is_archived: false,
    archived_at: null,
    archived_by: null,
    version: 3,
    can_update: true,
    github_link: null,
    account: { id: 'account-1', name: 'Acme' },
    account_links: [],
    evidence_count: 0,
    product_areas: [],
    created_by: 1,
    updated_by: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

function createDeferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve: (value: T) => void = () => undefined
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe('featureRequestGithubLogic', () => {
    let featureRequests: ReturnType<typeof featureRequestsLogic.build>
    let integrations: ReturnType<typeof integrationsLogic.build>
    let github: ReturnType<typeof featureRequestGithubLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/feature_requests/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/feature_requests/:id/': request,
                '/api/projects/:team_id/feature_request_product_areas/': [],
                '/api/projects/:team_id/accounts/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/integrations/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 12,
                            kind: 'github',
                            display_name: 'PostHog GitHub',
                            icon_url: '',
                            config: {},
                            created_at: '2026-01-01T00:00:00Z',
                        },
                    ],
                },
            },
        })
        initKeaTests(true, MOCK_DEFAULT_TEAM)
        featureRequests = featureRequestsLogic()
        integrations = integrationsLogic()
        github = featureRequestGithubLogic({ requestId: request.id })
        featureRequests.mount()
        integrations.mount()
        github.mount()
        featureRequests.actions.loadActiveRequestSuccess(request)
        await expectLogic(integrations, () => integrations.actions.loadIntegrations()).toFinishAllListeners()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        github.unmount()
        integrations.unmount()
        featureRequests.unmount()
    })

    it('links an issue through the active project URL', async () => {
        const updated = { ...request, version: 4 }
        const linkSpy = jest.spyOn(generatedApi, 'featureRequestsLinkGithubCreate').mockResolvedValueOnce(updated)
        github.actions.setIssueUrl('https://github.com/posthog/posthog/issues/81886')

        await expectLogic(github, () => github.actions.linkGithub()).toFinishAllListeners()

        expect(linkSpy).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), request.id, {
            integration_id: 12,
            issue_url: 'https://github.com/posthog/posthog/issues/81886',
            expected_version: 3,
        })
        expect(featureRequests.values.activeRequest).toEqual(updated)
        expect(github.values.issueUrl).toBe('')
    })

    it('does not send a duplicate link while the first request is pending', async () => {
        const pendingLink = createDeferred<FeatureRequestApi>()
        const linkStarted = createDeferred<void>()
        const linkSpy = jest.spyOn(generatedApi, 'featureRequestsLinkGithubCreate').mockImplementationOnce(() => {
            linkStarted.resolve()
            return pendingLink.promise
        })
        github.actions.setIssueUrl('https://github.com/posthog/posthog/issues/81886')

        github.actions.linkGithub()
        await linkStarted.promise
        github.actions.linkGithub()

        expect(linkSpy).toHaveBeenCalledTimes(1)
        pendingLink.resolve(request)
        await expectLogic(github).toFinishAllListeners()
    })

    it.each([
        ['read-only request', { ...request, can_update: false }],
        ['archived request', { ...request, is_archived: true }],
    ])('does not mutate a %s', async (_, inaccessibleRequest) => {
        featureRequests.actions.loadActiveRequestSuccess(inaccessibleRequest)
        github.actions.setIssueUrl('https://github.com/posthog/posthog/issues/81886')
        const linkSpy = jest.spyOn(generatedApi, 'featureRequestsLinkGithubCreate')
        const pauseSpy = jest.spyOn(generatedApi, 'featureRequestsPauseGithubCreate')
        const resumeSpy = jest.spyOn(generatedApi, 'featureRequestsResumeGithubCreate')
        const unlinkSpy = jest.spyOn(generatedApi, 'featureRequestsUnlinkGithubCreate')

        github.actions.linkGithub()
        github.actions.pauseGithub()
        github.actions.resumeGithub()
        github.actions.unlinkGithub()
        await expectLogic(github).toFinishAllListeners()

        expect(linkSpy).not.toHaveBeenCalled()
        expect(pauseSpy).not.toHaveBeenCalled()
        expect(resumeSpy).not.toHaveBeenCalled()
        expect(unlinkSpy).not.toHaveBeenCalled()
    })

    it.each([
        [
            'link an issue',
            () => github.actions.linkGithub(),
            () => jest.spyOn(generatedApi, 'featureRequestsLinkGithubCreate'),
        ],
        [
            'pause GitHub sync',
            () => github.actions.pauseGithub(),
            () => jest.spyOn(generatedApi, 'featureRequestsPauseGithubCreate'),
        ],
        [
            'resume GitHub sync',
            () => github.actions.resumeGithub(),
            () => jest.spyOn(generatedApi, 'featureRequestsResumeGithubCreate'),
        ],
        [
            'unlink an issue',
            () => github.actions.unlinkGithub(),
            () => jest.spyOn(generatedApi, 'featureRequestsUnlinkGithubCreate'),
        ],
    ] as const)('does not %s after the active request changes', async (_, mutate, createMutationSpy) => {
        github.actions.setIssueUrl('https://github.com/posthog/posthog/issues/81886')
        featureRequests.actions.loadActiveRequestSuccess({ ...request, id: 'request-2', version: 4 })
        const mutationSpy = createMutationSpy()

        mutate()
        await expectLogic(github).toFinishAllListeners()

        expect(mutationSpy).not.toHaveBeenCalled()
    })

    it('keeps the entered issue URL when linking fails', async () => {
        jest.spyOn(generatedApi, 'featureRequestsLinkGithubCreate').mockRejectedValueOnce(new ApiError('stale', 409))
        github.actions.setIssueUrl('https://github.com/posthog/posthog/issues/81886')

        await expectLogic(github, () => github.actions.linkGithub()).toFinishAllListeners()

        expect(github.values.issueUrl).toBe('https://github.com/posthog/posthog/issues/81886')
        expect(github.values.mutationIsStale).toBe(true)
    })

    it('does not replace a newly active request when a pending link completes', async () => {
        const pendingLink = createDeferred<FeatureRequestApi>()
        const linkStarted = createDeferred<void>()
        jest.spyOn(generatedApi, 'featureRequestsLinkGithubCreate').mockImplementationOnce(() => {
            linkStarted.resolve()
            return pendingLink.promise
        })
        github.actions.setIssueUrl('https://github.com/posthog/posthog/issues/81886')

        github.actions.linkGithub()
        await linkStarted.promise
        const otherRequest = { ...request, id: 'request-2', title: 'Keep this request active' }
        featureRequests.actions.loadActiveRequestSuccess(otherRequest)
        pendingLink.resolve({ ...request, title: 'Linked request response' })
        await expectLogic(github).toFinishAllListeners()

        expect(featureRequests.values.activeRequest).toEqual(otherRequest)
    })
})
