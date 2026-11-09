import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { importProjectHomepage } from './importProjectHomepage'

const loadedModules: string[] = []

jest.mock('./ProjectHomepage', () => {
    loadedModules.push('ProjectHomepage')
    return {}
})
jest.mock('./ai-first/AiFirstHomepage', () => {
    loadedModules.push('AiFirstHomepage')
    return {}
})
jest.mock('./today/TodayHome', () => {
    loadedModules.push('TodayHome')
    return {}
})

describe('importProjectHomepage', () => {
    beforeEach(() => {
        loadedModules.length = 0
        jest.resetModules()
    })

    it.each([
        [true, 'TodayHome'],
        [false, 'AiFirstHomepage'],
    ])('loads the home content with the scene (today on: %s)', async (todayOn, content) => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayOn })

        await importProjectHomepage()

        expect(loadedModules.sort()).toEqual([content, 'ProjectHomepage'].sort())
    })

    it.each([
        [true, 'TodayHome'],
        [false, 'AiFirstHomepage'],
    ])('loads the home content before the app mounts the flag logic (today on: %s)', async (todayOn, content) => {
        initKeaTests(false)
        jest.spyOn(posthog, 'isFeatureEnabled').mockImplementation(
            (flag) => flag === FEATURE_FLAGS.TODAY_RAIL_NAV && todayOn
        )

        await importProjectHomepage()

        expect(loadedModules.sort()).toEqual([content, 'ProjectHomepage'].sort())
        expect(featureFlagLogic.findMounted()).toBeNull()
    })
})
