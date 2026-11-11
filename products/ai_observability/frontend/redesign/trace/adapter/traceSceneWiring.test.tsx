import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { aiObservabilityTraceLogic } from '../../../aiObservabilityTraceLogic'
import { saveToDatasetButtonLogic } from '../../../datasets/saveToDatasetButtonLogic'
import type { TraceClusterApi } from '../../../generated/api.schemas'
import { queryEvaluationRuns } from '../../../utils'
import {
    decodeIdSegment,
    makeEvaluationResult,
    makeEvaluationResults,
    makeEvent,
    makeFeedback,
    makeFeedbackScore,
    makeFeedbackText,
    makeMessage,
    makeNodeDetail,
    makeRawNode,
    makeSurveyResponse,
    makeTrace,
    makeTraceCluster,
    makeTraceResource,
} from '../testFixtures'
import { traceReviewLogic } from '../traceReviewLogic'
import { TraceScene } from '../TraceScene'

const FLAG = FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN
const DATASETS_FLAG = FEATURE_FLAGS.LLM_ANALYTICS_DATASETS
const ENGINEERING_ANALYTICS_FLAG = FEATURE_FLAGS.ENGINEERING_ANALYTICS
const TRACE_NAVIGATION_FLAG = FEATURE_FLAGS.LLM_ANALYTICS_TRACE_NAVIGATION

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))
jest.mock('../../../utils', () => ({
    ...jest.requireActual('../../../utils'),
    queryEvaluationRuns: jest.fn().mockResolvedValue([]),
}))

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const NODE_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/'
const RAW_NODE_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/raw/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const CLUSTERS_URL = '/api/projects/:team_id/ai_observability/traces/:id/clusters/'
const FEEDBACK_URL = '/api/projects/:team_id/ai_observability/traces/:id/feedback/'
const DATASETS_URL = '/api/projects/:team_id/datasets/'
const EXPORT_URL = '/api/projects/:team_id/ai_observability/traces/:id/exports/'
const PULL_REQUEST_URL = '/api/projects/:team_id/ai_observability/traces/:id/pull_request/'
const SEARCH_URL = '/api/projects/:team_id/ai_observability/traces/:id/search/'
const SUMMARY_URL = '/api/projects/:team_id/ai_observability/traces/:id/summary/'
const REVIEW_URL = '/api/projects/:team_id/ai_observability/traces/:id/review/'
const REVIEW_QUEUES_URL = '/api/projects/:team_id/llm_analytics/review_queues/'
const QUEUE_ITEM_URL = '/api/projects/:team_id/llm_analytics/review_queue_items/:id/'
const answeredGeneration = makeNodeDetail({
    id: 'gen-2',
    content: {
        input: {
            kind: 'messages',
            messages: [
                makeMessage({
                    id: 'gen-2-in-0',
                    role: 'user',
                    parts: [{ kind: 'text', text: 'Why did my invoice go up?' }],
                }),
            ],
        },
        output: {
            kind: 'messages',
            messages: [
                makeMessage({
                    id: 'gen-2-out-0',
                    role: 'assistant',
                    parts: [{ kind: 'text', text: 'Two seats were added.' }],
                }),
            ],
        },
    },
})
const askedGeneration = makeNodeDetail({
    id: 'gen-1',
    content: {
        input: {
            kind: 'messages',
            messages: [
                makeMessage({
                    id: 'gen-1-in-0',
                    role: 'user',
                    parts: [{ kind: 'text', text: 'Is my invoice right?' }],
                }),
            ],
        },
        output: { kind: 'messages', messages: [] },
    },
})
const nodeDetails: Record<string, typeof answeredGeneration> = { 'gen-1': askedGeneration, 'gen-2': answeredGeneration }
let nodeRequests: string[] = []
let datasetListRequests = 0
const nodeMock = {
    [NODE_URL]: ({ params }: { params: Record<string, unknown> }) => {
        const nodeId = decodeIdSegment(String(params.node_id))
        nodeRequests.push(nodeId)
        return [200, nodeDetails[nodeId] ?? makeNodeDetail({ id: nodeId })]
    },
}
const evaluationsMock = { [EVALUATIONS_URL]: () => [200, makeEvaluationResults()] }
let clusters: TraceClusterApi[] = []
const clustersMock = { [CLUSTERS_URL]: () => [200, { clusters }] }
const feedbackMock = { [FEEDBACK_URL]: () => [200, makeFeedback({ scores: [], responses: [] })] }
const reviewMock = {
    [REVIEW_URL]: () => [200, { review: null, queue: null }],
    [REVIEW_QUEUES_URL]: () => [200, { count: 0, next: null, previous: null, results: [] }],
}

const generation = makeEvent({
    id: 'gen-1',
    event: '$ai_generation',
    createdAt: '2026-09-01T10:15:02Z',
    properties: {
        $ai_trace_id: 'trace-1',
        $ai_parent_id: 'trace-1',
        $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
        $ai_output_choices: [{ role: 'assistant', content: 'Two seats were added.' }],
    },
})

function findElement(container: HTMLElement, dataAttr: string): HTMLElement {
    const element = container.querySelector<HTMLElement>(`[data-attr="${dataAttr}"]`)
    if (!element) {
        throw new Error(`expected ${dataAttr} to render`)
    }
    return element
}

let accessToRestore: { saved: Record<AccessControlResourceType, AccessControlLevel> } | null = null

function renderNewView(
    flags: Record<string, boolean> = {},
    params: Record<string, string> = {},
    aiObservabilityAccess: AccessControlLevel | null = null
): ReturnType<typeof render> {
    initKeaTests()
    if (aiObservabilityAccess) {
        const appContext = window.POSTHOG_APP_CONTEXT!
        accessToRestore = { saved: appContext.resource_access_control }
        appContext.resource_access_control = {
            ...appContext.resource_access_control,
            llm_analytics: aiObservabilityAccess,
        }
    }
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags(
        Object.keys(flags).filter((flag) => flags[flag]),
        flags
    )
    nodeRequests = []
    datasetListRequests = 0
    jest.mocked(performQuery).mockReset()
    jest.mocked(performQuery).mockResolvedValue({ results: [] })
    aiObservabilityTraceLogic.mount()
    router.actions.push(urls.aiObservabilityTrace('trace-1', params))
    return render(<TraceScene />)
}

describe('TraceScene', () => {
    beforeEach(() => {
        clusters = []
    })

    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
        if (accessToRestore) {
            window.POSTHOG_APP_CONTEXT!.resource_access_control = accessToRestore.saved
            accessToRestore = null
        }
    })

    describe('the new view', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [TRACE_URL]: () => [200, makeTraceResource({ defaultNodeId: 'gen-2' })],
                    [DATASETS_URL]: () => {
                        datasetListRequests++
                        return [200, { count: 0, results: [] }]
                    },
                    [SEARCH_URL]: () => [200, { total: 1, matches: [{ nodeId: 'gen-1', count: 1 }] }],
                    ...nodeMock,
                    ...evaluationsMock,
                    ...clustersMock,
                    ...feedbackMock,
                    ...reviewMock,
                },
            })
        })

        it('opens on the default node without the legacy trace, neighbours or evaluation runs queries', async () => {
            const apiQuery = jest.spyOn(api, 'query').mockResolvedValue({ results: [] })
            const { findAllByText, findByText } = renderNewView({ [TRACE_NAVIGATION_FLAG]: true })

            expect((await findAllByText('answer-billing-question')).length).toBeGreaterThan(0)
            expect(await findByText('Two seats were added.')).toBeTruthy()
            await expectLogic(aiObservabilityTraceLogic).toFinishAllListeners()
            expect(jest.mocked(performQuery).mock.calls.some(([query]) => query.kind === 'TraceQuery')).toBe(false)
            expect(apiQuery.mock.calls.some(([query]) => query.kind === 'TraceNeighborsQuery')).toBe(false)
            expect(queryEvaluationRuns).not.toHaveBeenCalled()
            apiQuery.mockRestore()
        })

        it('starts another trace with an empty search, its own timestamp and Spans', async () => {
            const timestampHints: Record<string, string | null> = {}
            useMocks({
                get: {
                    [TRACE_URL]: ({ params, request }) => {
                        const traceId = decodeIdSegment(String(params.id))
                        timestampHints[traceId] = new URL(request.url).searchParams.get('timestamp_hint')
                        return [
                            200,
                            makeTraceResource({
                                defaultNodeId: 'gen-2',
                                name: traceId === 'trace-2' ? 'answer-refund-question' : 'answer-billing-question',
                            }),
                        ]
                    },
                },
            })
            const { container, findAllByText, findByText } = renderNewView({}, { search: 'invoice' })
            const treeRow = (): Element | null => container.querySelector('[data-attr="trace-view-tree-node"]')
            const searchInput = (): HTMLInputElement | null =>
                container.querySelector<HTMLInputElement>('input[data-attr="trace-view-search-input"]')

            fireEvent.click(await findByText('Thread'))
            await waitFor(() => expect(treeRow()).toBeNull())
            expect(searchInput()?.value).toBe('invoice')

            router.actions.push(urls.aiObservabilityTrace('trace-2', { timestamp: '2026-09-02T08:00:00Z' }))

            expect((await findAllByText('answer-refund-question')).length).toBeGreaterThan(0)
            expect(timestampHints['trace-2']).toBe('2026-09-02T08:00:00Z')
            expect(searchInput()?.value).toBe('')
            expect(treeRow()).not.toBeNull()
        })

        it.each([
            [
                'the header',
                200,
                (view: ReturnType<typeof render>): Promise<HTMLElement> =>
                    view.findByLabelText('Back to generations', { selector: '[data-attr="trace-view-back"]' }),
            ],
            [
                'the error screen',
                500,
                (view: ReturnType<typeof render>): Promise<HTMLElement> => view.findByText('Back to generations'),
            ],
        ])('links back to the list the trace came from on %s', async (_name, status, findBackLink) => {
            silenceKeaLoadersErrors()
            useMocks({
                get: {
                    [TRACE_URL]: () =>
                        status === 200 ? [200, makeTraceResource()] : [status, { detail: 'Server error.' }],
                },
            })

            const link = (await findBackLink(renderNewView({}, { back_to: 'generations' }))).closest('a')

            expect(link?.getAttribute('href')?.endsWith(urls.aiObservabilityGenerations())).toBe(true)
        })

        it('selects the step named in the URL', async () => {
            const { container } = renderNewView({}, { event: 'span-1' })

            await waitFor(() =>
                expect(
                    container.querySelector('[data-attr="trace-view-tree-node"][aria-current="true"]')?.textContent
                ).toContain('span-1')
            )
        })

        it('opens Summary from a tab=summary link', async () => {
            useMocks({
                get: {
                    [SUMMARY_URL]: () => [
                        200,
                        {
                            status: 'ready',
                            content: {
                                title: 'Invoice question answered',
                                bullets: [{ text: 'Context is retrieved first.', nodeId: 'span-1' }],
                                notes: [],
                                flow: 'retrieve → answer',
                                model: 'gpt-4.1-mini',
                                generatedAt: '2026-09-01T10:20:00Z',
                            },
                            failure: null,
                        },
                    ],
                },
            })
            const { findByText } = renderNewView({}, { tab: 'summary' })

            expect(await findByText('Context is retrieved first.')).toBeTruthy()
        })

        it('seeds the search box from the URL', async () => {
            const { container, findByText } = renderNewView({}, { search: 'invoice' })

            expect(await findByText('1 match')).toBeTruthy()
            expect(container.querySelector<HTMLInputElement>('input[data-attr="trace-view-search-input"]')?.value).toBe(
                'invoice'
            )
        })

        it('writes a clicked step to the URL', async () => {
            const { findByText } = renderNewView()

            fireEvent.click(await findByText('span-1'))

            await waitFor(() => expect(router.values.searchParams.event).toBe('span-1'))
        })

        it('starts reading a step when the pointer rests on its row', async () => {
            const { findByText } = renderNewView()
            const row = (await findByText('span-1')).closest('[data-attr="trace-view-tree-node"]')
            if (!row) {
                throw new Error('expected span-1 to render as a tree row')
            }
            nodeRequests = []

            fireEvent.mouseEnter(row)

            await waitFor(() => expect(nodeRequests).toContain('span-1'))
        })

        it('links the clusters chip to the cluster page', async () => {
            clusters = [
                makeTraceCluster({ runId: '1_trace_20260902_030000', clusterId: 3, title: 'Billing questions' }),
            ]
            const { findByText } = renderNewView()

            const chip = (await findByText('Billing questions')).closest('a')

            expect(
                chip?.getAttribute('href')?.endsWith(urls.aiObservabilityCluster('1_trace_20260902_030000', 3))
            ).toBe(true)
        })

        it('searches from the header, fades the steps without a match and steps to the match in view', async () => {
            const { container, findAllByText, findByText } = renderNewView()
            const treeRow = async (name: string): Promise<Element> => {
                const row = (await findAllByText(name))
                    .map((element) => element.closest('[data-attr="trace-view-tree-node"]'))
                    .find((element) => element !== null)
                if (!row) {
                    throw new Error(`expected ${name} to render as a tree row`)
                }
                return row
            }
            await treeRow('gen-1')
            const input = container.querySelector('input[data-attr="trace-view-search-input"]')
            if (!input) {
                throw new Error('expected the header to render the search input')
            }
            expect(input.getAttribute('maxlength')).toBe('200')

            fireEvent.change(input, { target: { value: 'invoice' } })

            expect(await findByText('1 match')).toBeTruthy()
            expect((await treeRow('gen-2')).className).toContain('opacity-50')
            expect((await treeRow('gen-1')).className).not.toContain('opacity-50')

            const scrollIntoView = jest.spyOn(Element.prototype, 'scrollIntoView')

            fireEvent.keyDown(input, { key: 'Enter' })

            const matchedRow = await treeRow('gen-1')
            await waitFor(() => expect(matchedRow.getAttribute('aria-current')).toBe('true'))
            const firstHighlight = await findByText('Is my invoice right?')
            await waitFor(() =>
                expect(scrollIntoView.mock.contexts).toEqual(expect.arrayContaining([matchedRow, firstHighlight]))
            )
            scrollIntoView.mockRestore()
        })

        it('the Summary tab shows a stored summary whose step link opens that step in spans', async () => {
            useMocks({
                get: {
                    [SUMMARY_URL]: () => [
                        200,
                        {
                            status: 'ready',
                            content: {
                                title: 'Invoice question answered',
                                bullets: [{ text: 'Context is retrieved first.', nodeId: 'span-1' }],
                                notes: [],
                                flow: 'retrieve → answer',
                                model: 'gpt-4.1-mini',
                                generatedAt: '2026-09-01T10:20:00Z',
                            },
                            failure: null,
                        },
                    ],
                },
            })
            const { container, findByText } = renderNewView()

            fireEvent.click(await findByText('Summary'))
            expect(await findByText('Context is retrieved first.')).toBeTruthy()
            fireEvent.click(await findByText('View step'))

            await waitFor(() =>
                expect(
                    container.querySelector('[data-attr="trace-view-tree-node"][aria-current="true"]')?.textContent
                ).toContain('span-1')
            )
        })

        it('opens the failing step on its Evals tab from the evals chip', async () => {
            useMocks({
                get: {
                    [EVALUATIONS_URL]: () => [
                        200,
                        makeEvaluationResults({
                            results: [
                                makeEvaluationResult({
                                    evaluationName: 'Cites a source',
                                    targetNodeId: 'gen-1',
                                    outcome: 'fail',
                                    label: 'False',
                                }),
                            ],
                            summary: {
                                passed: 0,
                                failed: 1,
                                unrated: 0,
                                nodes: [{ nodeId: 'gen-1', outcome: 'fail' }],
                            },
                        }),
                    ],
                },
            })
            const { findByText, queryByText } = renderNewView()
            const chip = await findByText('Evals 0/1 passed')
            expect(queryByText('Cites a source')).toBeNull()

            fireEvent.click(chip)

            expect(await findByText('Cites a source')).toBeTruthy()
        })

        it.each([
            [true, urls.engineeringAnalyticsPullRequest('acme', 'app', 42)],
            [false, null],
        ])(
            'shows the trace git branch, linked to its pull request when engineering analytics is on (%s)',
            async (enabled, expectedHref) => {
                useMocks({
                    get: {
                        [TRACE_URL]: () => [
                            200,
                            makeTraceResource({
                                defaultNodeId: 'gen-2',
                                git: { branch: 'feat/rag', repo: 'acme/app' },
                            }),
                        ],
                        [PULL_REQUEST_URL]: () => [
                            200,
                            { pullRequest: { repoOwner: 'acme', repoName: 'app', number: 42, title: null } },
                        ],
                    },
                })
                const { findByText, container } = renderNewView({ [ENGINEERING_ANALYTICS_FLAG]: enabled })

                expect(await findByText('feat/rag')).toBeTruthy()
                await waitFor(() =>
                    expect(
                        container
                            .querySelector('[data-attr="trace-view-git-pull-request-link"]')
                            ?.getAttribute('href') ?? null
                    ).toBe(expectedHref && addProjectIdIfMissing(expectedHref))
                )
            }
        )

        it('exports the trace with its time and shows the button as busy until the export starts', async () => {
            let releaseExport = (): void => {}
            const exportStarted = new Promise<void>((resolve) => {
                releaseExport = resolve
            })
            const exportBodies: unknown[] = []
            useMocks({
                post: {
                    [EXPORT_URL]: async ({ request }) => {
                        exportBodies.push(await request.json())
                        await exportStarted
                        return [
                            201,
                            {
                                id: 7,
                                status: 'pending',
                                filename: 'trace-1.json',
                                createdAt: '2026-09-01T10:20:00Z',
                                expiresAfter: null,
                                exception: null,
                            },
                        ]
                    },
                },
            })
            const { findByLabelText } = renderNewView()
            const button = (await findByLabelText('Export this trace as a JSON file')).closest('button')
            if (!button) {
                throw new Error('expected the export action to render as a button')
            }

            fireEvent.click(button)

            await waitFor(() => expect(exportBodies).toEqual([{ timestamp_hint: '2026-09-01T10:15:00Z' }]))
            expect(button.classList.contains('LemonButton--loading')).toBe(true)
            releaseExport()
            await waitFor(() => expect(button.classList.contains('LemonButton--loading')).toBe(false))
        })

        it.each([true, false])('offers add to dataset on the step only when datasets are on (%s)', async (enabled) => {
            const { findByText, queryByText } = renderNewView({ [DATASETS_FLAG]: enabled })

            expect(await findByText('Two seats were added.')).toBeTruthy()
            expect(queryByText('Add to dataset') !== null).toBe(enabled)
            expect(datasetListRequests > 0).toBe(enabled)
        })

        it('keeps the dataset list loaded while an unread step loads', async () => {
            const { findByText } = renderNewView({ [DATASETS_FLAG]: true })
            await findByText('Add to dataset')
            await waitFor(() => expect(datasetListRequests).toBeGreaterThan(0))
            const requestsBeforeStep = datasetListRequests

            fireEvent.click(await findByText('span-1'))
            await waitFor(() => expect(nodeRequests).toContain('span-1'))
            await findByText('Add to dataset')
            await expectLogic(saveToDatasetButtonLogic).toFinishAllListeners()

            expect(datasetListRequests).toBe(requestsBeforeStep)
        })

        it.each([
            { reach: 'hover', focused: false, opened: false },
            { reach: 'focus', focused: true, opened: false },
            { reach: 'click', focused: true, opened: true },
        ])(
            'reads the step event when the user reaches for add to dataset by $reach and keeps that intent',
            async ({ reach, focused, opened }) => {
                let releaseRaw = (): void => {}
                const rawReleased = new Promise<void>((resolve) => {
                    releaseRaw = resolve
                })
                const rawRequests: string[] = []
                useMocks({
                    get: {
                        [RAW_NODE_URL]: async ({ params }) => {
                            rawRequests.push(decodeIdSegment(String(params.node_id)))
                            await rawReleased
                            return [200, makeRawNode({ id: 'gen-2' })]
                        },
                    },
                })
                const { container } = renderNewView({ [DATASETS_FLAG]: true }, {}, AccessControlLevel.Editor)
                const placeholder = await waitFor(() => findElement(container, 'save-to-dataset-placeholder'))

                if (reach === 'hover') {
                    fireEvent.mouseEnter(placeholder)
                } else {
                    placeholder.focus()
                }
                if (reach === 'click') {
                    fireEvent.click(placeholder)
                }
                await waitFor(() => expect(rawRequests).toEqual(['gen-2']))
                releaseRaw()

                const realButton = await waitFor(() => findElement(container, 'save-to-dataset-open'))
                await waitFor(() => expect(document.activeElement === document.body).toBe(!focused))
                if (focused) {
                    expect(document.activeElement === realButton || opened).toBe(true)
                }
                await waitFor(() =>
                    expect(document.querySelector('[data-attr="save-to-dataset-search"]') !== null).toBe(opened)
                )
            }
        )

        it('does not carry a click on one step into the dataset button of the next step', async () => {
            useMocks({
                get: {
                    [RAW_NODE_URL]: ({ params }) => {
                        const nodeId = decodeIdSegment(String(params.node_id))
                        return [
                            200,
                            nodeId === 'gen-2'
                                ? makeRawNode({ id: nodeId, withEvent: false })
                                : makeRawNode({ id: nodeId, kind: 'span' }),
                        ]
                    },
                },
            })
            const { container, findByText } = renderNewView({ [DATASETS_FLAG]: true }, {}, AccessControlLevel.Editor)
            fireEvent.click(await waitFor(() => findElement(container, 'save-to-dataset-placeholder')))
            await waitFor(() => expect(container.querySelector('[data-attr="save-to-dataset-placeholder"]')).toBeNull())

            fireEvent.click(await findByText('span-1'))
            fireEvent.mouseEnter(await waitFor(() => findElement(container, 'save-to-dataset-placeholder')))
            await waitFor(() => findElement(container, 'save-to-dataset-open'))
            await expectLogic(saveToDatasetButtonLogic).toFinishAllListeners()

            expect(document.querySelector('[data-attr="save-to-dataset-search"]')).toBeNull()
        })

        it.each([
            {
                name: 'reviewed',
                status: {
                    review: {
                        reviewedBy: 'Ada',
                        reviewedAt: '2026-09-01T10:20:00Z',
                        comment: null,
                        scores: [{ name: 'Tone', value: '4.5', label: 'Tone: 4.5' }],
                    },
                    queue: null,
                },
                shown: ['Reviewed · 1 score', 'Edit review'],
                hidden: ['Add to queue', 'Change queue'],
            },
            {
                name: 'queued',
                status: { review: null, queue: { id: 'q1', name: 'Support QA', itemId: 'i1' } },
                shown: ['Support QA', 'Review', 'Change queue'],
                hidden: ['Edit review', 'Add to queue'],
            },
            {
                name: 'neither',
                status: { review: null, queue: null },
                shown: ['Review', 'Add to queue'],
                hidden: ['Edit review', 'Change queue'],
            },
        ])('shows the review state and its actions in the header when $name', async ({ status, shown, hidden }) => {
            useMocks({ get: { [REVIEW_URL]: () => [200, status] } })
            const { findByText, queryByText } = renderNewView()

            for (const text of shown) {
                expect(await findByText(text)).toBeTruthy()
            }
            for (const text of hidden) {
                expect(queryByText(text)).toBeNull()
            }
        })

        it('keeps Review and an open review modal through a failed status reload, and hides the queue picker', async () => {
            let reviewStatus = 200
            useMocks({
                get: {
                    [REVIEW_URL]: () =>
                        reviewStatus === 200
                            ? [200, { review: null, queue: { id: 'q1', name: 'Support QA', itemId: 'i1' } }]
                            : [500, { detail: 'nope' }],
                },
            })
            const { findByText, queryByText } = renderNewView({}, {}, AccessControlLevel.Editor)
            expect(await findByText('Change queue')).toBeTruthy()
            fireEvent.click(await findByText('Review'))
            expect(await findByText('Review trace')).toBeTruthy()

            silenceKeaLoadersErrors()
            reviewStatus = 500
            traceReviewLogic({ traceId: 'trace-1' }).actions.loadReviewStatus()

            await waitFor(() => expect(queryByText('Change queue')).toBeNull())
            expect(queryByText('Review trace')).toBeTruthy()
            expect(await findByText('Support QA')).toBeTruthy()
        })

        it('removes a queued trace from its queue from the queue chip, after confirming, and only once', async () => {
            const deleted: string[] = []
            let releaseDelete = (): void => {}
            const deleteGate = new Promise<void>((resolve) => {
                releaseDelete = resolve
            })
            useMocks({
                get: {
                    [REVIEW_URL]: () => [200, { review: null, queue: { id: 'q1', name: 'Support QA', itemId: 'i1' } }],
                },
                delete: {
                    [QUEUE_ITEM_URL]: async ({ params }) => {
                        deleted.push(String(params.id))
                        await deleteGate
                        return [204]
                    },
                },
            })
            const { container, findByText } = renderNewView({}, {}, AccessControlLevel.Editor)
            await findByText('Support QA')
            const remove = container.querySelector('[data-attr="trace-view-remove-from-queue"]')
            if (!remove) {
                throw new Error('expected a remove control on the queue chip')
            }

            fireEvent.click(remove)
            fireEvent.click(await findByText('Remove from queue'))

            await waitFor(() => expect(deleted).toEqual(['i1']))
            expect(container.querySelector('[data-attr="trace-view-remove-from-queue"]')).toBeNull()
            releaseDelete()
        })

        it('opens the feedback from the header chip and the step chips, and links each entry to its step', async () => {
            const helpfulness = makeFeedbackScore({ name: 'helpfulness', value: '0', nodeId: 'gen-1' })
            useMocks({
                get: {
                    [FEEDBACK_URL]: () => [
                        200,
                        makeFeedback({
                            scores: [helpfulness],
                            responses: [makeFeedbackText({ text: 'Too long, but correct.', nodeId: 'trace-1' })],
                            steps: [{ nodeId: 'gen-1', scores: [helpfulness], responseCount: 0, total: 1 }],
                        }),
                    ],
                },
            })
            const { container, findByText, getByText } = renderNewView()

            fireEvent.click(await findByText('Feedback 2', { selector: 'button *' }))
            expect(await findByText('Too long, but correct.')).toBeTruthy()

            fireEvent.click(getByText('gen-1', { selector: '[data-attr="trace-view-feedback-step-link"]' }))
            await waitFor(() =>
                expect(
                    container.querySelector('[data-attr="trace-view-tree-node"][aria-current="true"]')?.textContent
                ).toContain('gen-1')
            )

            fireEvent.click(await findByText('helpfulness 0'))
            expect(await findByText('What users said')).toBeTruthy()
        })

        it('shows thumbs in the header chip and the survey answers in the feedback', async () => {
            useMocks({
                get: {
                    [FEEDBACK_URL]: () => [
                        200,
                        makeFeedback({
                            scores: [],
                            responses: [makeSurveyResponse()],
                            summary: { total: 1, thumbsUp: 1, thumbsDown: 0 },
                        }),
                    ],
                },
            })
            const { findByLabelText, findByText } = renderNewView()

            fireEvent.click(await findByLabelText('1 thumbs up, 0 thumbs down, 1 feedback in total'))

            expect(await findByText('Answer quality')).toBeTruthy()
            expect(await findByText('Thumbs up')).toBeTruthy()
        })
    })

    describe('behind the flag gate', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [TRACE_URL]: () => [200, makeTraceResource()],
                    ...nodeMock,
                    ...evaluationsMock,
                    ...clustersMock,
                    ...feedbackMock,
                    ...reviewMock,
                },
            })
        })

        async function renderTraceRoute(flagEnabled: boolean): Promise<ReturnType<typeof render>> {
            localStorage.clear()
            initKeaTests()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: flagEnabled })
            jest.mocked(performQuery).mockResolvedValue({ results: [makeTrace({ events: [generation] })] })
            aiObservabilityTraceLogic.mount()
            router.actions.push(urls.aiObservabilityTrace('trace-1'))
            // The old scene reads the project id while its modules load, so the import must follow initKeaTests.
            const { scene } = await import('../../../AIObservabilityTraceScene')
            const TraceRoute = scene.component
            return render(<TraceRoute />)
        }

        it.each([
            ['new', true, '[data-attr="trace-view-tree-node"]', '.AIObservabilityTraceScene__wrapper'],
            ['old', false, '.AIObservabilityTraceScene__wrapper', '[data-attr="trace-view-tree-node"]'],
        ])('renders only the %s view when the flag is %s', async (_view, flagEnabled, shown, hidden) => {
            const { container } = await renderTraceRoute(flagEnabled)

            await waitFor(() => expect(container.querySelector(shown)).not.toBeNull())
            expect(container.querySelector(hidden)).toBeNull()
        })
    })
})
