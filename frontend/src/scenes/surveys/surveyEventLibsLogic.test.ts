import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { hasOnlyNonClientSideLibs, surveyEventLibsLogic } from './surveyEventLibsLogic'
import { surveyLogic } from './surveyLogic'

describe('surveyEventLibsLogic', () => {
    let logic: ReturnType<typeof surveyEventLibsLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    function useMockedLibs(libs: string[]): void {
        useMocks({
            get: {
                '/api/projects/:team_id/surveys': { results: [], count: 0 },
            },
            post: {
                '/api/environments/:team_id/query/:kind': () => [200, { results: [[libs]] }],
            },
        })
    }

    it.each([
        ['a server-side only event', ['posthog-python', 'posthog-node'], true],
        ['an event seen from both a backend and the web SDK', ['posthog-python', 'web'], false],
        ['a mobile-only event', ['posthog-ios'], false],
        ['an event with no libs recorded', [], false],
    ])('flags %s as server-side only: %s', (_name, libs: string[], expected: boolean) => {
        expect(hasOnlyNonClientSideLibs(libs)).toBe(expected)
    })

    it('reports events that only arrive from non-client SDKs', async () => {
        useMockedLibs(['posthog-python'])
        logic = surveyEventLibsLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadEventLibs(['order_shipped'])
        })
            .toDispatchActions(['loadEventLibsSuccess'])
            .toMatchValues({
                libsByEvent: { order_shipped: ['posthog-python'] },
                nonClientSideLibsByEvent: { order_shipped: ['posthog-python'] },
            })
    })

    it('loads the libs of trigger events picked in the survey editor', async () => {
        useMockedLibs(['web'])
        logic = surveyEventLibsLogic()
        logic.mount()
        const survey = surveyLogic({ id: 'new' })
        survey.mount()

        await expectLogic(survey, () => {
            survey.actions.setSurveyValue('conditions', {
                events: { values: [{ name: 'signed_up' }], repeatedActivation: false },
            })
        }).toDispatchActions([logic.actionCreators.loadEventLibs(['signed_up'])])

        await expectLogic(logic)
            .toDispatchActions(['loadEventLibsSuccess'])
            .toMatchValues({ libsByEvent: { signed_up: ['web'] }, nonClientSideLibsByEvent: {} })

        survey.unmount()
    })
})
