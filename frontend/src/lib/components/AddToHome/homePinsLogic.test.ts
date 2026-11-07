import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

import type { PulsePinApi } from 'products/today/frontend/generated/api.schemas'

import { homePinsLogic } from './homePinsLogic'

const pin = (shortId: string): PulsePinApi => ({ key: `insight:${shortId}`, name: shortId, dashboard_id: null })
const insight = { short_id: 'new' as InsightShortId, name: 'Signups' }

describe('homePinsLogic', () => {
    let storedPins: PulsePinApi[]
    let savedPins: PulsePinApi[][]

    beforeEach(() => {
        savedPins = []
        useMocks({
            get: { '/api/projects/:team_id/today/pulse_pins/': () => [200, { pins: storedPins }] },
            put: {
                '/api/projects/:team_id/today/pulse_pins/': async ({ request }) => {
                    const { pins } = (await request.json()) as { pins: PulsePinApi[] }
                    savedPins.push(pins)
                    return [200, { pins }]
                },
            },
        })
        initKeaTests()
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        {
            name: 'adds the insight after the existing pins',
            stored: [pin('a')],
            label: { pinned: false, disabledReason: undefined },
            saved: [[pin('a'), { key: 'insight:new', name: 'Signups', dashboard_id: null }]],
            event: 'today pulse number pinned',
        },
        {
            name: 'removes a pinned insight even when the home is full',
            stored: [pin('a'), pin('new'), pin('c'), pin('d')],
            label: { pinned: true, disabledReason: undefined },
            saved: [[pin('a'), pin('c'), pin('d')]],
            event: 'today pulse number unpinned',
        },
        {
            name: 'does not add a fifth number',
            stored: [pin('a'), pin('b'), pin('c'), pin('d')],
            label: { pinned: false, disabledReason: 'Your home already shows 4 numbers. Remove one first.' },
            saved: [],
            event: null,
        },
    ])('$name', async ({ stored, label, saved, event }) => {
        storedPins = stored
        const logic = homePinsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.homePinState(insight)).toEqual(label)

        logic.actions.toggleHomePin(insight, 'dashboard_card')
        await expectLogic(logic).toFinishAllListeners()

        expect(savedPins).toEqual(saved)
        if (event) {
            expect(posthog.capture).toHaveBeenCalledWith(event, {
                kind: 'insight',
                source: 'dashboard_card',
                pinned_count_before: stored.length,
            })
        } else {
            expect(posthog.capture).not.toHaveBeenCalled()
        }
    })
})
