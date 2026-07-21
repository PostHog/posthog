import { expectLogic } from 'kea-test-utils'
import posthogJs from 'posthog-js'

import typedPosthog from 'lib/posthog-typed'

import { initKeaTests } from '~/test/init'

import { featureFlagLogic, getFeatureFlagPayload } from './featureFlagLogic'
import { membersLogic } from './membersLogic'
import shimmedPosthog from './posthogTyped'
import { sceneLogic } from './sceneLogic'
import { surveyQuestionLabelsLogic } from './surveyQuestionLabelsLogic'
import { isAuthenticatedTeam, teamLogic } from './teamLogic'
import { userLogic } from './userLogic'

describe('toolbar shims', () => {
    beforeEach(() => {
        initKeaTests(false)
    })

    describe('default values', () => {
        it.each([
            ['userLogic', userLogic, { user: null, themeMode: 'system' }],
            ['membersLogic', membersLogic, { members: [] }],
            ['sceneLogic', sceneLogic, { sceneConfig: null }],
            ['teamLogic', teamLogic, { currentTeam: null, timezone: 'UTC', weekStartDay: 0 }],
            ['featureFlagLogic', featureFlagLogic, { featureFlags: {} }],
            ['surveyQuestionLabelsLogic', surveyQuestionLabelsLogic, { surveyQuestionLabels: {} }],
        ])('%s provides expected defaults', (_name, logic, expected) => {
            logic.mount()
            expectLogic(logic).toMatchValues(expected)
        })
    })

    describe('actions are callable without side effects', () => {
        it.each([
            ['userLogic.updateUser', () => userLogic.mount() && userLogic.actions.updateUser({})],
            ['userLogic.loadUserSuccess', () => userLogic.mount() && userLogic.actions.loadUserSuccess({})],
            [
                'membersLogic.ensureAllMembersLoaded',
                () => membersLogic.mount() && membersLogic.actions.ensureAllMembersLoaded(),
            ],
        ])('%s does not throw', (_name, fn) => {
            expect(fn).not.toThrow()
        })
    })

    it('sceneLogic exposes sceneConfig selector for direct reference', () => {
        sceneLogic.mount()
        expect(typeof sceneLogic.selectors.sceneConfig).toBe('function')
    })

    it('no shim triggers fetch when mounted', () => {
        const fetchSpy = jest.fn()
        global.fetch = fetchSpy

        userLogic.mount()
        membersLogic.mount()
        sceneLogic.mount()
        teamLogic.mount()
        featureFlagLogic.mount()
        surveyQuestionLabelsLogic.mount()

        expect(fetchSpy).not.toHaveBeenCalled()
    })

    describe('isAuthenticatedTeam', () => {
        it.each([
            [null, false],
            [undefined, false],
            [{}, false],
            [{ api_token: 'phc_abc123' }, true],
        ])('isAuthenticatedTeam(%j) returns %s', (input, expected) => {
            expect(isAuthenticatedTeam(input)).toBe(expected)
        })
    })

    describe('getFeatureFlagPayload', () => {
        it.each([['SOME_FLAG'], ['ANOTHER_FLAG'], ['']])('returns undefined for %s', (flag) => {
            expect(getFeatureFlagPayload(flag)).toBeUndefined()
        })
    })

    describe('posthogTyped shim', () => {
        it('exposes every runtime member lib/posthog-typed adds beyond posthog-js', () => {
            // The toolbar build swaps lib/posthog-typed for the shim, invisible to the
            // typechecker — if the generator grows a new runtime method, the shim must too,
            // or toolbar code calling it crashes on customer pages.
            for (const key of Object.keys(typedPosthog)) {
                expect(typeof (shimmedPosthog as any)[key]).toBe(typeof (typedPosthog as any)[key])
            }
        })

        it.each([['capture'], ['captureRaw']] as const)('%s delegates to posthog-js capture', (method) => {
            const captureSpy = jest.spyOn(posthogJs, 'capture').mockReturnValue(undefined)
            shimmedPosthog[method]('some event', { foo: 'bar' })
            expect(captureSpy).toHaveBeenCalledWith('some event', { foo: 'bar' }, undefined)
            captureSpy.mockRestore()
        })
    })
})
