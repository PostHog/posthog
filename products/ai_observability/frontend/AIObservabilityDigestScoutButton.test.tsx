import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import type { ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    AIObservabilityDigestScoutButton,
    getAIObservabilityDigestScoutInitialValues,
} from './AIObservabilityDigestScoutButton'

jest.mock('scenes/inbox/components/config/scouts/ScoutCreateButton', () => ({
    ScoutCreateButton: ({ children }: { children: ReactNode }) => <button>{children}</button>,
}))

describe('AIObservabilityDigestScoutButton', () => {
    let unmountFeatureFlagLogic: (() => void) | null = null

    beforeEach(() => {
        initKeaTests()
        unmountFeatureFlagLogic = featureFlagLogic.mount()
    })

    afterEach(() => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        unmountFeatureFlagLogic?.()
        unmountFeatureFlagLogic = null
        cleanup()
    })

    it.each([
        { enabled: false, visible: false },
        { enabled: true, visible: true },
    ])('is visible=$visible when the AI observability feature flag is enabled=$enabled', ({ enabled, visible }) => {
        featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.AI_OBSERVABILITY_DAILY_DIGEST_SCOUT] : [], {
            [FEATURE_FLAGS.AI_OBSERVABILITY_DAILY_DIGEST_SCOUT]: enabled,
        })

        render(
            <Provider>
                <AIObservabilityDigestScoutButton />
            </Provider>
        )

        expect(Boolean(screen.queryByRole('button', { name: 'Create daily digest' }))).toBe(visible)
    })

    it('prefills a daily 9 a.m. scout that discovers the dashboard and produces one actionable digest', () => {
        const initialValues = getAIObservabilityDigestScoutInitialValues()

        expect(initialValues).toMatchObject({
            name: 'signals-scout-ai-observability-daily-digest',
            config: {
                enabled: true,
                emit: true,
                run_interval_minutes: 1440,
                run_cron_schedule: '0 9 * * *',
            },
        })
        expect(initialValues.body).toEqual(expect.stringContaining('dashboards-get-all'))
        expect(initialValues.body).not.toEqual(expect.stringContaining('dashboard ID'))
        expect(initialValues.body).toEqual(expect.stringContaining('posthog:exploring-ai-failures'))
        expect(initialValues.body).toEqual(expect.stringContaining('posthog:analyzing-expensive-users'))
        expect(initialValues.body).toEqual(expect.stringContaining('posthog:exploring-llm-evaluations'))
        expect(initialValues.body).toEqual(expect.stringContaining('Do not repeat an unchanged issue'))
        expect(initialValues.body).toEqual(expect.stringContaining('Create at most one report per run'))
        expect(initialValues.body).toEqual(
            expect.stringContaining('Every included item must lead to a concrete next action')
        )
    })
})
