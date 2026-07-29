import { render, screen } from '@testing-library/react'

import { Experiment } from '~/types'

import { ExperimentFlagKeyInput } from './ExperimentFlagKeyInput'

describe('ExperimentFlagKeyInput', () => {
    const runningExperiment = {
        id: 1,
        name: 'Pricing page test',
        start_date: '2026-01-01T00:00:00Z',
        end_date: null,
        feature_flag: { id: 5, key: 'pricing-page-test' },
    } as unknown as Experiment

    const baseProps = {
        onFlagKeyChange: () => {},
        sourceExperiment: runningExperiment,
        featureFlags: { results: [], count: 0 },
        featureFlagsLoading: false,
        featureFlagFilters: {},
        onFeatureFlagFiltersChange: () => {},
        featureFlagPagination: { controlled: true as const, pageSize: 30, currentPage: 1, entryCount: 0 },
        onSelectExistingFlag: () => {},
        showReuseFlag: false,
        onToggleReuseFlag: () => {},
    }

    it('does not warn when a new flag key will be created, even for a running experiment', () => {
        render(
            <ExperimentFlagKeyInput
                {...baseProps}
                flagKey="pricing-page-test-copy"
                isExistingFlag={false}
                reusesSourceFlag={false}
            />
        )

        expect(screen.queryByText(/side effects/)).toBeNull()
    })

    it('warns that reusing the source flag keeps existing variant assignments and mixes results', () => {
        render(
            <ExperimentFlagKeyInput
                {...baseProps}
                flagKey="pricing-page-test"
                isExistingFlag={true}
                reusesSourceFlag={true}
            />
        )

        expect(screen.getByText(/keeps that variant/)).toBeTruthy()
        expect(screen.getByText(/Pricing page test is still running/)).toBeTruthy()
    })

    it('warns generically when reusing a flag other than the source experiment flag', () => {
        render(
            <ExperimentFlagKeyInput
                {...baseProps}
                flagKey="some-other-flag"
                isExistingFlag={true}
                reusesSourceFlag={false}
            />
        )

        expect(screen.getByText(/If another experiment uses this flag/)).toBeTruthy()
    })
})
