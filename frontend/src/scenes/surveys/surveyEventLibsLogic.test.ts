import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { hasOnlyNonClientSideLibs, surveyEventLibsLogic } from './surveyEventLibsLogic'
import { surveyLogic } from './surveyLogic'

describe('surveyEventLibsLogic', () => {
    let logic: ReturnType<typeof surveyEventLibsLogic.build>
    let survey: ReturnType<typeof surveyLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        survey?.unmount()
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

    function mountWithTriggerEvent(eventName: string): void {
        survey = surveyLogic({ id: 'new' })
        survey.mount()
        logic = surveyEventLibsLogic({ id: 'new' })
        logic.mount()
        survey.actions.setSurveyValue('conditions', {
            events: { values: [{ name: eventName }], repeatedActivation: false },
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

    it('reports a trigger event that only arrives from non-client SDKs', async () => {
        useMockedLibs(['posthog-python'])
        mountWithTriggerEvent('order_shipped')

        await expectLogic(logic)
            .toDispatchActions([logic.actionCreators.loadEventLibs(['order_shipped']), 'loadEventLibsSuccess'])
            .toMatchValues({
                libsByEvent: { order_shipped: ['posthog-python'] },
                nonClientSideLibsByEvent: { order_shipped: ['posthog-python'] },
            })
    })

    it('stays quiet for a trigger event the web SDK captures', async () => {
        useMockedLibs(['web'])
        mountWithTriggerEvent('signed_up')

        await expectLogic(logic)
            .toDispatchActions(['loadEventLibsSuccess'])
            .toMatchValues({ libsByEvent: { signed_up: ['web'] }, nonClientSideLibsByEvent: {} })
    })
})
