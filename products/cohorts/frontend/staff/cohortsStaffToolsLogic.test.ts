import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { cohortsStaffToolsLogic, parseCohortIds } from './cohortsStaffToolsLogic'

describe('cohortsStaffToolsLogic', () => {
    describe('parseCohortIds', () => {
        it.each([
            ['128418, 34012', [128418, 34012]],
            ['128418, 128418, 34012', [128418, 34012]], // dedupes, preserving order
            ['128418 34012\n99', [128418, 34012, 99]], // tolerant of space/newline separators
            ['', []],
            ['no ids here', []],
            ['-123', []], // rejects rather than silently parsing as cohort 123
            ['123.5', []], // rejects rather than silently parsing as cohorts 123 and 5
            ['123, -456, 789', [123, 789]], // malformed tokens are dropped, valid ones still parsed
        ])('parses %s as %s', (input, expected) => {
            expect(parseCohortIds(input)).toEqual(expected)
        })
    })

    describe('deep link seeding', () => {
        let logic: ReturnType<typeof cohortsStaffToolsLogic.build>

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/cohorts_staff/': { results: [], not_found_cohort_ids: [] },
                    '/api/cohorts_staff/stuck/': { results: [], total_count: 0 },
                },
            })
            initKeaTests()
            logic = cohortsStaffToolsLogic()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('seeds the input and looks up the cohort from a deep link', async () => {
            router.actions.push('/feature_flags/staff/cohorts?cohort_id=123')
            await expectLogic(logic).toDispatchActions([
                'seedCohortFromDeepLink',
                'lookUpCohorts',
                'lookUpCohortsSuccess',
            ])
            expectLogic(logic).toMatchValues({ cohortIdsInput: '123' })
        })

        it('does not clobber a manual edit when the URL is revisited with the same cohort id', async () => {
            router.actions.push('/feature_flags/staff/cohorts?cohort_id=123')
            await expectLogic(logic).toDispatchActions(['seedCohortFromDeepLink'])

            logic.actions.setCohortIdsInput('456')
            // Simulates urlToAction re-running for the same URL, e.g. browser back/forward.
            router.actions.push('/feature_flags/staff/cohorts?cohort_id=123')

            expectLogic(logic).toMatchValues({ cohortIdsInput: '456' })
        })

        it('re-seeds when a different cohort id is deep-linked while already seeded', async () => {
            router.actions.push('/feature_flags/staff/cohorts?cohort_id=123')
            await expectLogic(logic).toDispatchActions(['seedCohortFromDeepLink'])

            router.actions.push('/feature_flags/staff/cohorts?cohort_id=456')
            await expectLogic(logic).toDispatchActions(['seedCohortFromDeepLink'])

            expectLogic(logic).toMatchValues({ cohortIdsInput: '456' })
        })
    })

    describe('afterMount', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/cohorts_staff/stuck/': { results: [], total_count: 0 },
                },
            })
            initKeaTests()
            userLogic.mount()
        })

        it('loads stuck cohorts for a staff user', async () => {
            userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: true })

            const logic = cohortsStaffToolsLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadStuckCohorts', 'loadStuckCohortsSuccess'])
        })

        it('does not load stuck cohorts for a non-staff user hitting the URL directly', () => {
            // The scene component itself blocks non-staff users with an AccessDenied page, but this
            // logic mounts regardless (it's the scene's kea logic). Fetching anyway would 403 and
            // surface a misleading error toast on top of AccessDenied.
            userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: false })

            const logic = cohortsStaffToolsLogic()
            logic.mount()

            expect(logic.values.stuckResponseLoading).toBe(false)
        })
    })
})
