import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { globalSetupLogic } from './globalSetupLogic'
import type { QuickStartTrigger } from './types'

describe('globalSetupLogic quick start analytics', () => {
    let logic: ReturnType<typeof globalSetupLogic.build>
    let captureSpy: jest.SpyInstance

    const trigger: QuickStartTrigger = { surface: 'scene_title', minimized: false, remainingCount: 4 }

    beforeEach(() => {
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        logic = globalSetupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    const capturedEvents = (event: string): unknown[] =>
        captureSpy.mock.calls.filter(([name]) => name === event).map(([, properties]) => properties)

    it('captures quick start opened when the user opens the popover', async () => {
        await expectLogic(logic, () => {
            logic.actions.openGlobalSetup({ ...trigger, source: 'shortcut' })
        }).toFinishAllListeners()

        expect(logic.values.isGlobalModalOpen).toBe(true)
        expect(capturedEvents('quick start opened')).toEqual([
            {
                product: ProductKey.PRODUCT_ANALYTICS,
                source: 'shortcut',
                surface: 'scene_title',
                minimized: false,
                remaining_count: 4,
            },
        ])
    })

    // Completing a task re-opens the popover without a trigger, which is not a user open
    it('does not capture quick start opened for an internal re-open', async () => {
        await expectLogic(logic, () => {
            logic.actions.openGlobalSetup()
        }).toFinishAllListeners()

        expect(logic.values.isGlobalModalOpen).toBe(true)
        expect(capturedEvents('quick start opened')).toEqual([])
    })

    it('captures quick start shown once per product', async () => {
        await expectLogic(logic, () => {
            logic.actions.reportQuickStartShown(ProductKey.PRODUCT_ANALYTICS, trigger)
            logic.actions.reportQuickStartShown(ProductKey.PRODUCT_ANALYTICS, { ...trigger, remainingCount: 3 })
            logic.actions.reportQuickStartShown(ProductKey.SESSION_REPLAY, { ...trigger, minimized: true })
        }).toFinishAllListeners()

        expect(capturedEvents('quick start shown')).toEqual([
            { product: ProductKey.PRODUCT_ANALYTICS, surface: 'scene_title', minimized: false, remaining_count: 4 },
            { product: ProductKey.SESSION_REPLAY, surface: 'scene_title', minimized: true, remaining_count: 4 },
        ])
    })
})
