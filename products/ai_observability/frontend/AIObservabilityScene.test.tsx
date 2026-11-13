import { RenderResult, act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'

import { shortcutLogic } from 'lib/components/Shortcuts/shortcutLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { emptySceneParams } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { AIObservabilityGenerations, AIObservabilityScene } from './AIObservabilityScene'
import { traceDrawerLogic } from './redesign/trace/traceDrawerLogic'

jest.mock('./AIObservabilityTracesScene', () => ({ AIObservabilityTraces: () => <div data-attr="traces-body" /> }))
jest.mock('./AIObservabilitySessionsPlaylist', () => ({
    AIObservabilitySessionsPlaylist: () => <div data-attr="sessions-body" />,
}))
jest.mock('./traceReviews/AIObservabilityHumanReviews', () => ({
    AIObservabilityHumanReviews: () => <div data-attr="reviews-body" />,
}))
jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))

const GENERATIONS_PATH = urls.aiObservabilityGenerations()
const NAV = FEATURE_FLAGS.AI_OBSERVABILITY_NAV_REDESIGN
const FRAME_TABS = '[data-attr="ai-observability-tabs"]'
const TABBED_BAR = '[data-attr="llm-analytics-tabs"]'
const DRAWER_TIMESTAMP = '2026-01-01T11:55:00Z'
const PERSON = { uuid: 'person-1', distinct_id: 'user-1', properties: {} }

function generationRow(uuid: string | null, traceId: string): unknown[] {
    return [uuid, traceId, PERSON, 'gpt-4', null, '', '1 s', '1 → 1 (∑ 2)', '$0.1', '2026-01-01T12:00:00Z']
}

async function renderGenerations({ url = GENERATIONS_PATH } = {}): Promise<RenderResult> {
    initKeaTests()
    localStorage.clear()
    jest.mocked(performQuery).mockReset()
    jest.mocked(performQuery).mockImplementation(async (query) =>
        query.kind === NodeKind.EventsQuery
            ? { results: [generationRow('gen-1', 'trace-1'), generationRow(null, 'trace-2')] }
            : { results: [] }
    )
    featureFlagLogic.mount()
    panelLayoutLogic.mount()
    router.actions.push(url)
    const view = render(<AIObservabilityGenerations />)
    await waitFor(() => expect(view.container.querySelector('[data-attr="generation-id-link"]')).not.toBeNull())
    return view
}

function renderScene({
    sceneKey,
    url = urls.aiObservabilityTraces(),
    flags = [NAV],
}: {
    sceneKey: string
    url?: string
    flags?: string[]
}): HTMLElement {
    initKeaTests()
    localStorage.clear()
    jest.mocked(performQuery).mockReset()
    jest.mocked(performQuery).mockImplementation(async () => ({ results: [] }))
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    router.actions.push(url)
    sceneLogic.mount()
    sceneLogic.actions.setScene('AIObservability', sceneKey, emptySceneParams)
    return render(<AIObservabilityScene />).container
}

function activeFrameTabs(container: HTMLElement): (string | null | undefined)[] {
    return Array.from(container.querySelectorAll(`${FRAME_TABS} [role="tab"][aria-selected="true"]`)).map((tab) =>
        tab.querySelector('[data-attr^="ai-observability-tab-"]')?.getAttribute('data-attr')
    )
}

function activeScopes(container: HTMLElement): (string | null)[] {
    return Array.from(
        container.querySelectorAll('.LemonSegmentedButton__option--selected [data-attr^="ai-observability-scope-"]')
    ).map((option) => option.getAttribute('data-attr'))
}

function frameHref(container: HTMLElement, dataAttr: string): string {
    const found = container.querySelector(`[data-attr="${dataAttr}"]`)
    return (found?.closest('a') ?? found?.querySelector('a'))?.getAttribute('href') ?? ''
}

function element(view: RenderResult, selector: string): Element {
    const found = view.container.querySelector(selector)
    if (!found) {
        throw new Error(`No ${selector}`)
    }
    return found
}

function row(view: RenderResult): Element {
    const found = element(view, '[data-attr="generation-id-link"]').closest('tr')
    if (!found) {
        throw new Error('No row')
    }
    return found
}

describe('AIObservabilityScene', () => {
    afterEach(cleanup)

    it('leaves the trace drawer params out of the tab links and keeps the filters', () => {
        initKeaTests()
        router.actions.push(`${urls.aiObservabilityTraces()}?date_from=-7d&trace=a&ts=2026&step=x`)

        const { container } = render(<AIObservabilityScene />)

        const href = container.querySelector('[data-attr="generations-tab"]')?.closest('a')?.getAttribute('href')
        expect(href).toContain(`${urls.aiObservabilityGenerations()}?date_from=-7d`)
        expect(href).not.toMatch(/trace=|ts=|step=/)
    })

    describe('with the navigation flag on', () => {
        it.each([
            ['aiObservabilityTraces', 'ai-observability-scope-traces', 'traces-body'],
            ['aiObservabilitySessions', 'ai-observability-scope-sessions', 'sessions-body'],
        ])('wraps the body of %s in the frame', (sceneKey, scope, body) => {
            const container = renderScene({ sceneKey })

            expect(container.querySelector(TABBED_BAR)).toBeNull()
            expect(activeFrameTabs(container)).toEqual(['ai-observability-tab-activity'])
            expect(activeScopes(container)).toEqual([scope])
            expect(container.querySelector(`[data-attr="${body}"]`)).not.toBeNull()
        })

        it('renders a page with no tab inside the frame with none active', () => {
            const container = renderScene({ sceneKey: 'aiObservabilityReviews', url: urls.aiObservabilityReviews() })

            expect(container.querySelector(FRAME_TABS)).not.toBeNull()
            expect(activeFrameTabs(container)).toEqual([])
            expect(container.querySelector('[data-attr="reviews-body"]')).not.toBeNull()
        })

        it('leaves the trace drawer params out of the frame links and keeps the filters', () => {
            const container = renderScene({
                sceneKey: 'aiObservabilityTraces',
                url: `${urls.aiObservabilityTraces()}?date_from=-7d&trace=a&ts=2026&step=x`,
            })

            const href = frameHref(container, 'ai-observability-tab-diagnostics')
            expect(href).toContain(`${urls.aiObservabilityErrors()}?date_from=-7d`)
            expect(href).not.toMatch(/trace=|ts=|step=/)
        })

        it('moves to the other scope with the filters and without the trace drawer params', () => {
            const container = renderScene({
                sceneKey: 'aiObservabilityTraces',
                url: `${urls.aiObservabilityTraces()}?date_from=-7d&trace=a&ts=2026&step=x`,
            })

            const sessions = container.querySelector('[data-attr="ai-observability-scope-sessions"]')
            if (!sessions) {
                throw new Error('No sessions option')
            }
            fireEvent.click(sessions)

            expect(router.values.location.pathname).toContain(urls.aiObservabilitySessions())
            expect(router.values.searchParams).toEqual({ date_from: '-7d' })
        })

        it.each([
            [1, urls.aiObservabilityDashboard()],
            [2, urls.aiObservabilityTraces()],
            [3, urls.aiObservabilityErrors()],
            [4, urls.aiObservabilityUsers()],
        ])('sends tab shortcut %i to its tab with the filters and without the drawer params', (position, path) => {
            renderScene({
                sceneKey: 'aiObservabilitySessions',
                url: `${urls.aiObservabilitySessions()}?date_from=-7d&trace=a&ts=2026&step=x`,
            })
            const shortcut = shortcutLogic.values.registeredShortcuts.find(
                ({ name }) => name === `AIObservabilityTab${position}`
            )

            act(() => shortcut?.callback?.())

            expect(router.values.location.pathname).toContain(path)
            expect(router.values.searchParams).toEqual({ date_from: '-7d' })
        })

        it('registers no fifth tab shortcut', () => {
            renderScene({ sceneKey: 'aiObservabilityTraces' })

            expect(shortcutLogic.values.registeredShortcuts.map(({ name }) => name)).not.toContain(
                'AIObservabilityTab5'
            )
        })

        it('shows the not-found page for self-driving when its flag is off', () => {
            const container = renderScene({
                sceneKey: 'aiObservabilitySelfDriving',
                url: urls.aiObservabilitySelfDriving(),
            })

            expect(container.querySelector('[data-attr="not-found-page"]')).not.toBeNull()
            expect(container.querySelector(FRAME_TABS)).toBeNull()
        })
    })

    it('swaps to the frame when the navigation flag arrives after mount', () => {
        const container = renderScene({ sceneKey: 'aiObservabilityTraces', flags: [] })
        expect(container.querySelector(TABBED_BAR)).not.toBeNull()
        expect(container.querySelector(FRAME_TABS)).toBeNull()

        act(() => featureFlagLogic.actions.setFeatureFlags([NAV], { [NAV]: true }))

        expect(container.querySelector(TABBED_BAR)).toBeNull()
        expect(activeFrameTabs(container)).toEqual(['ai-observability-tab-activity'])
        expect(container.querySelector('[data-attr="traces-body"]')).not.toBeNull()
    })

    describe('opening the trace drawer from generations', () => {
        it.each([
            ['the row', (view: RenderResult): Element => row(view).querySelectorAll('td')[3]],
            ['the ID link', (view: RenderResult): Element => element(view, '[data-attr="generation-id-link"]')],
            ['the trace link', (view: RenderResult): Element => element(view, '[data-attr="generation-trace-link"]')],
        ])('opens on the generation from a plain click on %s', async (_name, target) => {
            const view = await renderGenerations()

            fireEvent.click(target(view))

            expect(router.values.location.pathname).toContain(GENERATIONS_PATH)
            expect(router.values.searchParams).toMatchObject({
                trace: 'trace-1',
                ts: DRAWER_TIMESTAMP,
                step: 'gen-1',
            })
        })

        it('gives the drawer the rows that have ids', async () => {
            await renderGenerations()
            const logic = traceDrawerLogic({ listId: 'generations' })

            await waitFor(() =>
                expect(logic.values.rows).toEqual([
                    { traceId: 'trace-1', timestamp: DRAWER_TIMESTAMP, stepId: 'gen-1' },
                ])
            )
        })

        it('expands a row without opening the drawer', async () => {
            const view = await renderGenerations()
            const expander = row(view).querySelector('button')
            if (!expander) {
                throw new Error('No expander')
            }

            fireEvent.click(expander)

            expect(router.values.searchParams).not.toHaveProperty('trace')
        })

        // A remounted link cannot take focus back when the drawer closes.
        it('keeps the same ID link in the document when the drawer writes the URL', async () => {
            const view = await renderGenerations()
            const link = element(view, '[data-attr="generation-id-link"]')

            act(() => router.actions.push(GENERATIONS_PATH, { trace: 'trace-1' }))

            expect(element(view, '[data-attr="generation-id-link"]')).toBe(link)
            expect(link.isConnected).toBe(true)
        })

        it('leaves the drawer params out of the ID link', async () => {
            const view = await renderGenerations({
                url: combineUrl(GENERATIONS_PATH, { trace: 'trace-2', ts: DRAWER_TIMESTAMP, step: 'gen-2' }).url,
            })

            const link = element(view, '[data-attr="generation-id-link"]').getAttribute('href') ?? ''

            expect(combineUrl(link).searchParams).toMatchObject({ back_to: 'generations', event: 'gen-1' })
            expect(combineUrl(link).searchParams).not.toHaveProperty('trace')
            expect(combineUrl(link).searchParams).not.toHaveProperty('step')
        })
    })
})
