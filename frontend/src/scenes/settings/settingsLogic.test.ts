import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { settingsLogic } from './settingsLogic'

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
}))

describe('settingsLogic self-host gating', () => {
    // Managed reverse proxy needs proxy infrastructure that only PostHog Cloud runs, so a
    // self-hosted instance must not be offered the section at all.
    it.each([
        ['a self-hosted instance', false, false],
        ['PostHog Cloud', true, true],
    ])('offers managed reverse proxy on %s: %s', async (_name, cloud, expected) => {
        useMocks({ get: { '/_preflight': { cloud, is_debug: false, realm: 'hosted_clickhouse' } } })
        initKeaTests()
        preflightLogic.mount()
        const logic = settingsLogic({ logicKey: 'self-host-gating-test' })
        logic.mount()

        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])

        expect(logic.values.sections.some((section) => section.id === 'organization-proxy')).toBe(expected)
    })
})
