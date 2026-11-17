import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
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

describe('CohortFlagTargetingNotice', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': () => [200, toPaginatedResponse([cohort()])],
                '/api/projects/:team_id/cohorts/:id/': () => [200, cohort()],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
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

    it('lists a cohort once when the set names it twice', async () => {
        await renderNotice(readiness('off'), [cohortCondition(1), cohortCondition('1')])

        await waitFor(() => {
            expect(screen.getAllByText('Turn on realtime')).toHaveLength(1)
        })
    })
})
