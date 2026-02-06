import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'

import { noveltyContentAdLogic } from './noveltyContentAdLogic'

describe('noveltyContentAdLogic', () => {
    let logic: ReturnType<typeof noveltyContentAdLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/': () => [200, MOCK_DEFAULT_TEAM],
            },
        })
        logic = noveltyContentAdLogic()
        logic.mount()
    })

    it('initializes with a random ad', () => {
        expect(logic.values.currentAd).toBeTruthy()
        expect(logic.values.currentAd.title).toBeTruthy()
        expect(logic.values.currentAd.description).toBeTruthy()
        expect(logic.values.currentAd.price).toBeTruthy()
        expect(logic.values.currentAd.cta).toBeTruthy()
    })

    it('is disabled by default', () => {
        expect(logic.values.isEnabled).toBe(false)
    })

    it('is not dismissed by default', () => {
        expect(logic.values.isDismissed).toBe(false)
    })

    it('can be toggled', async () => {
        await expectLogic(logic, () => {
            logic.actions.toggleEnabled()
        }).toMatchValues({
            isEnabled: true,
        })

        await expectLogic(logic, () => {
            logic.actions.toggleEnabled()
        }).toMatchValues({
            isEnabled: false,
        })
    })

    it('can be dismissed', async () => {
        await expectLogic(logic, () => {
            logic.actions.dismissAd()
        }).toMatchValues({
            isDismissed: true,
        })
    })

    it('can show next ad', async () => {
        const initialIndex = logic.values.currentAdIndex

        await expectLogic(logic, () => {
            logic.actions.showNextAd()
        }).toMatchValues({
            currentAdIndex: (initialIndex + 1) % logic.values.allAds.length,
        })
    })

    it('has 12 different ads available', () => {
        expect(logic.values.allAds.length).toBe(12)
    })
})
