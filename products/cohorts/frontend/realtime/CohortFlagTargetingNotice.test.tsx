import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { toPaginatedResponse } from '~/mocks/handlers'
import { useMocks } from '~/mocks/jest'
import { cohortsModel } from '~/models/cohortsModel'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { CohortRealtimeReadinessApi } from '../generated/api.schemas'
import { CohortFlagTargetingNotice } from './CohortFlagTargetingNotice'

const readiness = (
    state: CohortRealtimeReadinessApi['state'],
    overrides: Partial<CohortRealtimeReadinessApi> = {}
): CohortRealtimeReadinessApi => ({
    state,
    ready_at: null,
    build: null,
    reason: null,
    history_limit_days: null,
    ...overrides,
})

const cohortCondition = (value: number | string): AnyPropertyFilter =>
    ({ type: PropertyFilterType.Cohort, key: 'id', value, operator: PropertyOperator.In }) as AnyPropertyFilter

let served: CohortRealtimeReadinessApi | null
let listed: boolean

const cohort = (): Record<string, unknown> => ({
    id: 1,
    name: 'Viewed pricing this week',
    is_static: served?.state === 'static',
    filters: { properties: { type: 'AND', values: [] } },
    realtime: served,
})

async function renderNotice(
    realtime: CohortRealtimeReadinessApi | null,
    properties: AnyPropertyFilter[] = [cohortCondition(1)]
): Promise<HTMLElement> {
    served = realtime
    cohortsModel.mount()
    await expectLogic(cohortsModel).toFinishAllListeners()
    return render(
        <Provider>
            <CohortFlagTargetingNotice properties={properties} />
        </Provider>
    ).container
}

const setPageHidden = (hidden: boolean): void => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    act(() => {
        document.dispatchEvent(new Event('visibilitychange'))
    })
}

describe('CohortFlagTargetingNotice', () => {
    beforeEach(() => {
        listed = true
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': () => [200, toPaginatedResponse(listed ? [cohort()] : [])],
                '/api/projects/:team_id/cohorts/:id/': () => [200, cohort()],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        delete (document as any).hidden
    })

    it.each([
        { name: 'off', realtime: readiness('off'), turnOn: true, planLimits: false },
        {
            name: 'off over the history limit',
            realtime: readiness('off', { reason: 'history_over_limit', history_limit_days: 30 }),
            turnOn: false,
            planLimits: true,
        },
        { name: 'building', realtime: readiness('building'), turnOn: false, planLimits: false },
        { name: 'rebuilding', realtime: readiness('rebuilding'), turnOn: false, planLimits: false },
        { name: 'needs_attention', realtime: readiness('needs_attention'), turnOn: false, planLimits: false },
        { name: 'daily', realtime: readiness('daily'), turnOn: false, planLimits: false },
    ])('offers only what a person can do for a cohort that is $name', async ({ realtime, turnOn, planLimits }) => {
        await renderNotice(realtime)

        await waitFor(() => {
            expect(screen.getByText('Viewed pricing this week')).toBeInTheDocument()
        })
        expect(!!screen.queryByText('Turn on realtime')).toBe(turnOn)
        expect(!!screen.queryByText('See plan limits')).toBe(planLimits)
    })

    it.each([
        { name: 'ready', realtime: readiness('ready') },
        { name: 'matched on person properties', realtime: readiness('person_properties') },
        { name: 'static', realtime: readiness('static') },
        { name: 'outside the realtime rollout', realtime: null },
    ])('says nothing about a cohort that is $name', async ({ realtime }) => {
        const container = await renderNotice(realtime)

        expect(container).toBeEmptyDOMElement()
    })

    it('turns realtime on from the row and then shows the cohort preparing', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/cohorts/:id/realtime/': () => {
                    served = readiness('building')
                    return [200, cohort()]
                },
            },
        })
        await renderNotice(readiness('off'))

        fireEvent.click(await screen.findByText('Turn on realtime'))

        expect(await screen.findByText(/PostHog is preparing/)).toBeInTheDocument()
    })

    it('reads a cohort created after the shared model listed cohorts', async () => {
        listed = false

        await renderNotice(readiness('off'))

        expect(await screen.findByText('Turn on realtime')).toBeInTheDocument()
    })

    it('reads a cohort the shared model missed again when the tab comes back after its read failed', async () => {
        listed = false
        let readFails = true
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/:id/': () => (readFails ? [500, {}] : [200, cohort()]),
            },
        })
        await renderNotice(readiness('off'))
        await expectLogic(cohortsModel).toDispatchActions(['loadCohortsByIdsFailure'])
        readFails = false

        setPageHidden(true)
        setPageHidden(false)

        expect(await screen.findByText('Turn on realtime')).toBeInTheDocument()
    })

    it('lists a cohort once when the set names it twice', async () => {
        await renderNotice(readiness('off'), [cohortCondition(1), cohortCondition('1')])

        await waitFor(() => {
            expect(screen.getAllByText('Turn on realtime')).toHaveLength(1)
        })
    })
})
