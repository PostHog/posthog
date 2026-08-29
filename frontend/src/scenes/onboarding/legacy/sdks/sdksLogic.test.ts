import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { SDKTag } from '~/types'

import { ALL_SDKS } from './allSDKs'
import {
    ErrorTrackingSDKDocsLinkOverrides,
    ErrorTrackingSDKInstructions,
} from './error-tracking/ErrorTrackingSDKInstructions'
import { sdksLogic } from './sdksLogic'

describe('sdksLogic', () => {
    let logic: ReturnType<typeof sdksLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
        logic = sdksLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    const configureErrorTrackingSDKs = (): void => {
        logic.actions.setSDKDocsLinkOverrides(ErrorTrackingSDKDocsLinkOverrides)
        logic.actions.setAvailableSDKInstructionsMap(ErrorTrackingSDKInstructions)
    }

    it.each([
        ['before', false],
        ['after', true],
    ])('applies product docs overrides when the URL selects an SDK %s configuration', async (_, configureFirst) => {
        if (configureFirst) {
            configureErrorTrackingSDKs()
        }

        await expectLogic(logic, () => {
            router.actions.push('/onboarding/error_tracking?sdk=convex')
        }).toDispatchActions(['setSelectedSDK'])

        if (!configureFirst) {
            configureErrorTrackingSDKs()
        }

        expect(logic.values.selectedSDK?.docsLink).toBe('https://posthog.com/docs/libraries/convex')
    })

    describe('filteredSDKs', () => {
        const keysFor = (): string[] => logic.values.filteredSDKs.map((sdk) => sdk.key)

        beforeEach(() => {
            logic.actions.setSDKs(ALL_SDKS)
        })

        it('matches on the SDK name', () => {
            logic.actions.setSearchTerm('python')
            expect(keysFor()).toContain('python')
        })

        it('matches on a search alias that the name does not contain', () => {
            logic.actions.setSearchTerm('iphone')
            expect(keysFor()).toEqual(['ios'])
        })

        it('empties the grid when the tag and the search term exclude each other', () => {
            logic.actions.setSelectedTag(SDKTag.MOBILE)
            logic.actions.setSearchTerm('python')
            expect(logic.values.filteredSDKs).toHaveLength(0)
        })

        it('restores the full list once the search and tag are cleared', () => {
            logic.actions.setSelectedTag(SDKTag.MOBILE)
            logic.actions.setSearchTerm('python')
            logic.actions.setSearchTerm('')
            logic.actions.setSelectedTag(null)
            expect(logic.values.filteredSDKs).toHaveLength(ALL_SDKS.length)
        })
    })
})
