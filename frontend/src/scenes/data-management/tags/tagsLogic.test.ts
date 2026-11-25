import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TAG_PAGE_SIZE, tagsLogic } from './tagsLogic'

const source = { id: '00000000-0000-0000-0000-000000000001', name: 'customers', usage_count: 2 }
const target = { id: '00000000-0000-0000-0000-000000000002', name: 'customer', usage_count: 1 }

describe('tagsLogic', () => {
    let logic: ReturnType<typeof tagsLogic.build>
    let listRequests: number

    beforeEach(() => {
        initKeaTests()
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: OrganizationMembershipLevel.Admin,
        })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAG_MANAGEMENT], {
            [FEATURE_FLAGS.TAG_MANAGEMENT]: true,
        })
        listRequests = 0
        useMocks({
            get: {
                '/api/projects/:projectId/tag_definitions/': () => {
                    listRequests += 1
                    return { count: 2, next: null, previous: null, results: [source, target] }
                },
                '/api/projects/:projectId/tag_definitions/:id/merge_preview/': {
                    source_count: 2,
                    target_count: 1,
                    overlap_count: 1,
                    result_count: 2,
                    tag: target,
                },
            },
        })
        logic = tagsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it.each(['flag', 'member'])('refuses loading and actions when blocked by %s', async (boundary) => {
        await expectLogic(logic).toFinishAllListeners()
        if (boundary === 'flag') {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TAG_MANAGEMENT]: false })
        } else {
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                membership_level: OrganizationMembershipLevel.Member,
            })
        }
        const before = listRequests
        await expectLogic(logic, () => {
            logic.actions.loadTagDefinitions()
            logic.actions.submitMerge()
        }).toFinishAllListeners()
        expect(logic.values.canManageTags).toBe(false)
        expect(logic.values.tagPage).toBeNull()
        expect(listRequests).toBe(before)
    })

    it('prevents duplicate merge requests and refreshes after success', async () => {
        let resolveMerge!: () => void
        const pending = new Promise<void>((resolve) => {
            resolveMerge = resolve
        })
        let mergeRequests = 0
        useMocks({
            post: {
                '/api/projects/:projectId/tag_definitions/:id/merge/': async ({ request }) => {
                    expect(request.headers.get('X-PostHog-Environment-Id')).toBe(String(logic.values.currentTeamId))
                    mergeRequests += 1
                    await pending
                    return { moved_count: 1, overlap_count: 1, usage_count: 2, tag: { ...target, usage_count: 2 } }
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.openMerge(source)
            logic.actions.setTarget(target)
        }).toFinishAllListeners()
        logic.actions.submitMerge()
        logic.actions.submitMerge()
        expect(logic.values.mutationLoading).toBe(true)
        const before = listRequests
        resolveMerge()
        await expectLogic(logic).toFinishAllListeners()
        expect(mergeRequests).toBe(1)
        expect(logic.values.tagToMerge).toBeNull()
        expect(listRequests).toBeGreaterThan(before)
        expect(logic.values.mutationLoading).toBe(false)
        expect(logic.values.mutation).toBe('merge')
    })

    it('keeps a failed merge open, invalidates the preview, and allows retry', async () => {
        let attempts = 0
        useMocks({
            post: {
                '/api/projects/:projectId/tag_definitions/:id/merge/': () => {
                    attempts += 1
                    return attempts === 1
                        ? [404, { detail: 'Destination no longer exists.' }]
                        : { moved_count: 1, overlap_count: 1, usage_count: 2, tag: target }
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.openMerge(source)
            logic.actions.setTarget(target)
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.submitMerge()).toFinishAllListeners()
        expect(logic.values.tagToMerge).toEqual(source)
        expect(logic.values.preview).toBeNull()
        expect(logic.values.target).toBeNull()
        expect(logic.values.mutationError).toBeTruthy()
        expect(logic.values.mutationLoading).toBe(false)
        await expectLogic(logic, () => logic.actions.setTarget(target)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.submitMerge()).toFinishAllListeners()
        expect(attempts).toBe(2)
        expect(logic.values.tagToMerge).toBeNull()
    })

    it('waits for the project ID and uses it instead of the child environment ID', async () => {
        await expectLogic(logic).toFinishAllListeners()
        projectLogic.actions.loadCurrentProjectSuccess(null)
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 123 })
        expect(logic.values.currentProjectId).toBeNull()
        const paths: string[] = []
        const environments: (string | null)[] = []
        useMocks({
            get: {
                '/api/projects/:projectId/tag_definitions/': ({ request }) => {
                    paths.push(new URL(request.url).pathname)
                    environments.push(request.headers.get('X-PostHog-Environment-Id'))
                    return { count: 1, results: [source] }
                },
            },
            patch: {
                '/api/projects/:projectId/tag_definitions/:id/': ({ request }) => {
                    paths.push(new URL(request.url).pathname)
                    environments.push(request.headers.get('X-PostHog-Environment-Id'))
                    return source
                },
            },
        })
        await expectLogic(logic, () => logic.actions.loadTagDefinitions()).toFinishAllListeners()
        expect(paths).toEqual([])
        await expectLogic(logic, () =>
            projectLogic.actions.loadCurrentProjectSuccess({ ...MOCK_DEFAULT_PROJECT, id: 45 })
        ).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.openRename(source)
            logic.actions.setRenameName('renamed')
            logic.actions.submitRename()
        }).toFinishAllListeners()
        expect(paths).toEqual([
            '/api/projects/45/tag_definitions/',
            `/api/projects/45/tag_definitions/${source.id}/`,
            '/api/projects/45/tag_definitions/',
        ])
        expect(environments).toEqual(['123', '123', '123'])
    })

    it('reconciles a lost merge response before offering retry and closes if the source is gone', async () => {
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.openMerge(source)
            logic.actions.setTarget(target)
        }).toFinishAllListeners()
        let mergeRequests = 0
        let checkedSource = false
        useMocks({
            post: {
                '/api/projects/:projectId/tag_definitions/:id/merge/': () => {
                    mergeRequests++
                    return [502, {}]
                },
            },
            get: {
                [`/api/projects/:projectId/tag_definitions/${source.id}/`]: () => {
                    checkedSource = true
                    return [404, { detail: 'Not found.' }]
                },
                '/api/projects/:projectId/tag_definitions/': () => ({ count: 1, results: [target] }),
            },
        })
        await expectLogic(logic, () => logic.actions.submitMerge()).toFinishAllListeners()
        expect(checkedSource).toBe(true)
        expect(logic.values.mutationError).toBe('This tag is no longer available. Check the refreshed list.')
        expect(logic.values.tagPage?.results).toEqual([target])
        expect(logic.values.tagToMerge).toBeNull()
        expect(logic.values.canSubmitMerge).toBe(false)
        logic.actions.submitMerge()
        expect(mergeRequests).toBe(1)
    })

    it('recognizes a rename that committed before the response was lost', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const renamed = { ...source, name: 'renamed' }
        useMocks({
            patch: { '/api/projects/:projectId/tag_definitions/:id/': [502, {}] },
            get: {
                [`/api/projects/:projectId/tag_definitions/${source.id}/`]: renamed,
                '/api/projects/:projectId/tag_definitions/': { count: 1, results: [renamed] },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.openRename(source)
            logic.actions.setRenameName(' Renamed ')
            logic.actions.submitRename()
        }).toFinishAllListeners()
        expect(logic.values.tagToRename).toBeNull()
        expect(logic.values.mutationError).toBeNull()
        expect(logic.values.tagPage?.results).toEqual([renamed])
    })

    it('retries the failed destination page without dropping the loaded tags', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const firstPage = Array.from({ length: TAG_PAGE_SIZE }, (_, index) => ({
            ...target,
            id: `example-${index}`,
            name: `Example ${index}`,
        }))
        const offsets: number[] = []
        useMocks({
            get: {
                '/api/projects/:projectId/tag_definitions/': ({ request }) => {
                    const offset = Number(new URL(request.url).searchParams.get('offset'))
                    offsets.push(offset)
                    if (!offset) {
                        return { count: TAG_PAGE_SIZE + 1, next: '?offset=100', results: firstPage }
                    }
                    if (offsets.length === 2) {
                        return [503, {}]
                    }
                    return { count: TAG_PAGE_SIZE + 1, next: null, results: [target] }
                },
            },
        })
        await expectLogic(logic, () => logic.actions.openMerge(source)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadMoreDestinations()).toFinishAllListeners()
        expect(logic.values.destinationError).not.toBeNull()
        expect(logic.values.destinations).toEqual(firstPage)
        await expectLogic(logic, () => logic.actions.retryDestinations()).toFinishAllListeners()
        expect(logic.values.destinationError).toBeNull()
        expect(logic.values.destinations).toEqual([...firstPage, target])
        expect(offsets).toEqual([0, TAG_PAGE_SIZE, TAG_PAGE_SIZE])
    })

    it.each([
        ['list', 'succeeded'],
        ['list', 'pending'],
        ['destinations', 'succeeded'],
        ['destinations', 'pending'],
        ['preview', 'succeeded'],
        ['preview', 'pending'],
    ] as const)('discards a superseded %s failure when the newer request is %s', async (requestType, newerState) => {
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.openMerge(source)
            logic.actions.setTarget(target)
        }).toFinishAllListeners()

        let releaseFailure!: () => void
        const pendingFailure = new Promise<void>((resolve) => {
            releaseFailure = resolve
        })
        let markStarted!: () => void
        const started = new Promise<void>((resolve) => {
            markStarted = resolve
        })
        let releaseSuccess!: () => void
        const pendingSuccess = new Promise<void>((resolve) => {
            releaseSuccess = resolve
        })
        let markNewerStarted!: () => void
        const newerStarted = new Promise<void>((resolve) => {
            markNewerStarted = resolve
        })
        let requests = 0
        const result =
            requestType === 'preview'
                ? { source_count: 2, target_count: 1, overlap_count: 1, result_count: 2, tag: target }
                : { count: 1, next: null, previous: null, results: [target] }
        const path =
            requestType === 'preview'
                ? '/api/projects/:projectId/tag_definitions/:id/merge_preview/'
                : '/api/projects/:projectId/tag_definitions/'
        useMocks({
            get: {
                [path]: async () => {
                    requests += 1
                    if (requests === 1) {
                        markStarted()
                        await pendingFailure
                        return [503, {}]
                    }
                    markNewerStarted()
                    if (newerState === 'pending') {
                        await pendingSuccess
                    }
                    return result
                },
            },
        })
        const load = {
            list: () => logic.asyncActions.loadTagDefinitions(),
            destinations: () => logic.asyncActions.loadTagDestinations({}),
            preview: () => logic.asyncActions.loadTagMergePreview({ sourceId: source.id, targetId: target.id }),
        }[requestType]

        const olderRequest = load()
        await started
        const newerRequest = load()
        await newerStarted
        if (newerState === 'succeeded') {
            await newerRequest
        }
        releaseFailure()
        await olderRequest

        expect(logic.values.listError).toBeNull()
        expect(logic.values.destinationError).toBeNull()
        expect(logic.values.previewError).toBeNull()
        const loading = {
            list: logic.values.tagPageLoading,
            destinations: logic.values.destinationPageLoading,
            preview: logic.values.previewLoading,
        }[requestType]
        expect(loading).toBe(newerState === 'pending')

        releaseSuccess()
        await newerRequest
        const currentResult = {
            list: logic.values.tagPage,
            destinations: logic.values.destinationPage,
            preview: logic.values.preview,
        }[requestType]
        expect(currentResult).toEqual(result)
    })
})
