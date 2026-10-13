import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import * as alertsApi from 'products/alerts/frontend/generated/api'

import * as aiObservabilityApi from '../generated/api'
import { aiObservabilitySelfDrivingLogic } from './aiObservabilitySelfDrivingLogic'

jest.mock('../generated/api', () => ({
    llmAnalyticsEvaluationReportsList: jest.fn(),
}))

jest.mock('products/alerts/frontend/generated/api', () => ({
    alertsList: jest.fn(),
}))

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutConfigList: jest.fn(() => new Promise(() => {})),
    signalsScoutMetadataGet: jest.fn(() => new Promise(() => {})),
}))

const SELF_DRIVING_URL = '/ai-observability/self-driving'

describe('aiObservabilitySelfDrivingLogic', () => {
    let logic: ReturnType<typeof aiObservabilitySelfDrivingLogic.build>

    beforeEach(() => {
        silenceKeaLoadersErrors()
        initKeaTests()
        jest.mocked(alertsApi.alertsList).mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        } as any)
        jest.mocked(aiObservabilityApi.llmAnalyticsEvaluationReportsList).mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        } as any)
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
        jest.clearAllMocks()
    })

    const mountAt = (hash: Record<string, string>): void => {
        router.actions.push(SELF_DRIVING_URL, {}, hash)
        logic = aiObservabilitySelfDrivingLogic()
        logic.mount()
    }

    it.each([
        ['a known template key', { template: 'costly-users' }, 'costly-users'],
        ['a second known template key', { template: 'error-patterns' }, 'error-patterns'],
        ['an unknown template key', { template: 'not-a-template' }, null],
        ['no template key at all', {}, null],
    ])('opens the template %s names, and nothing else', (_label, hash, expected) => {
        mountAt(hash)

        expect(logic.values.openScoutTemplateKey).toBe(expected)
    })

    it('tells the reader when a link names a template that does not exist', () => {
        // The fragment is stripped before the lookup, so without this the reader is left with a
        // page that silently ignored their link.
        const toastError = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)

        mountAt({ template: 'not-a-template' })

        expect(toastError).toHaveBeenCalledTimes(1)
        toastError.mockRestore()
    })

    it('strips the template fragment so a refresh does not reopen the modal', () => {
        mountAt({ template: 'daily-digest', other: 'kept' })

        expect(router.values.hashParams).toEqual({ other: 'kept' })
    })
})
