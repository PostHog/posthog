import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'

import * as growthApi from 'products/growth/frontend/generated/api'
import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { navPanelProductPushLogic } from './navPanelProductPushLogic'

const MOCK_CAMPAIGN: ProductPushCampaignApi = {
    id: '0197c2a2-0000-0000-0000-000000000000',
    product_key: 'session_replay',
    product_path: 'Session replay',
    reason_text: 'Watch real sessions.',
    started_at: '2026-07-01T00:00:00Z',
    ends_at: '2026-07-31T00:00:00Z',
}

describe('navPanelProductPushLogic', () => {
    let logic: ReturnType<typeof navPanelProductPushLogic.build>

    beforeEach(async () => {
        initKeaTests()
        // The loader is gated on isCloudOrDev, so wait for cloud-ness to be known
        // (the default preflight fixture has is_debug=true → isCloudOrDev=true)
        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads the active campaign for the current organization on mount', async () => {
        const retrieve = jest.spyOn(growthApi, 'productPushCampaignActiveRetrieve').mockResolvedValue(MOCK_CAMPAIGN)

        logic = navPanelProductPushLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadActiveCampaign', 'loadActiveCampaignSuccess'])
            .toMatchValues({ activeCampaign: MOCK_CAMPAIGN })
        // The current team id rides along so the backend can hide the campaign per project
        expect(retrieve).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ team_id: expect.any(Number) })
        )
    })

    it.each([
        ['a 204 no-content response', () => Promise.resolve(undefined)],
        ['a request failure', () => Promise.reject(new Error('boom'))],
    ])('exposes null (without throwing) for %s', async (_name, response) => {
        jest.spyOn(growthApi, 'productPushCampaignActiveRetrieve').mockImplementation(response as any)

        logic = navPanelProductPushLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadActiveCampaignSuccess'])
            .toMatchValues({ activeCampaign: null })
    })
})
