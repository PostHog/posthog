import { RenderResult, act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { AIObservabilityGenerations, AIObservabilityScene } from './AIObservabilityScene'
import { traceDrawerLogic } from './redesign/trace/traceDrawerLogic'

jest.mock('./AIObservabilityTracesScene', () => ({ AIObservabilityTraces: () => null }))
jest.mock('./AIObservabilitySessionsPlaylist', () => ({ AIObservabilitySessionsPlaylist: () => null }))
jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))

const GENERATIONS_PATH = urls.aiObservabilityGenerations()
const DRAWER_TIMESTAMP = '2026-01-01T11:55:00Z'
const PERSON = { uuid: 'person-1', distinct_id: 'user-1', properties: {} }

function generationRow(uuid: string | null, traceId: string): unknown[] {
    return [uuid, traceId, PERSON, 'gpt-4', null, '', '1 s', '1 → 1 (∑ 2)', '$0.1', '2026-01-01T12:00:00Z']
}

async function renderGenerations({ flag = true, url = GENERATIONS_PATH } = {}): Promise<RenderResult> {
    initKeaTests()
    localStorage.clear()
    jest.mocked(performQuery).mockReset()
    jest.mocked(performQuery).mockImplementation(async (query) =>
        query.kind === NodeKind.EventsQuery
            ? { results: [generationRow('gen-1', 'trace-1'), generationRow(null, 'trace-2')] }
            : { results: [] }
    )
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN], {
        [FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN]: flag,
    })
    panelLayoutLogic.mount()
    router.actions.push(url)
    const view = render(<AIObservabilityGenerations />)
    await waitFor(() => expect(view.container.querySelector('[data-attr="generation-id-link"]')).not.toBeNull())
    return view
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

        it('keeps the row and its links as they were when the drawer is disabled', async () => {
            const view = await renderGenerations({ flag: false })

            fireEvent.click(row(view).querySelectorAll('td')[3])
            expect(router.values.location.pathname).toContain(GENERATIONS_PATH)

            fireEvent.click(element(view, '[data-attr="generation-trace-link"]'))
            expect(router.values.location.pathname).toContain(urls.aiObservabilityTrace('trace-1'))
            expect(router.values.searchParams).not.toHaveProperty('trace')
        })
    })
})
