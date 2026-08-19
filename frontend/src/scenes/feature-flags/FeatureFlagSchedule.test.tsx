import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType, ScheduledChangeOperationType } from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import FeatureFlagSchedule from './FeatureFlagSchedule'

jest.mock('./FeatureFlagReleaseConditionsCollapsible', () => ({
    FeatureFlagReleaseConditionsCollapsible: () => null,
}))
jest.mock('./FeatureFlagVariantsForm', () => ({ FeatureFlagVariantsForm: () => null }))

const MULTIVARIATE_FILTERS: FeatureFlagType['filters']['multivariate'] = {
    variants: [
        { key: 'control', name: 'Control', rollout_percentage: 50 },
        { key: 'test', name: 'Test', rollout_percentage: 50 },
    ],
}

function buildFeatureFlag({
    active,
    rolloutPercentage,
}: {
    active: boolean
    rolloutPercentage: number | null
}): FeatureFlagType {
    return {
        ...NEW_FLAG,
        id: 1,
        active,
        filters: {
            ...NEW_FLAG.filters,
            groups: [{ properties: [], rollout_percentage: rolloutPercentage, variant: null }],
            multivariate: MULTIVARIATE_FILTERS,
        },
    }
}

describe('FeatureFlagSchedule', () => {
    const logicProps = { id: 'new' as const }

    function renderSchedule(featureFlag: FeatureFlagType, operation: ScheduledChangeOperationType): void {
        const logic = featureFlagLogic(logicProps)

        render(
            <Provider>
                <BindLogic logic={featureFlagLogic} props={logicProps}>
                    <FeatureFlagSchedule />
                </BindLogic>
            </Provider>
        )

        act(() => {
            logic.actions.setFeatureFlag(featureFlag)
            logic.actions.setScheduledChangeOperation(operation)
        })
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/default_evaluation_contexts/': {
                    default_evaluation_contexts: [],
                    available_contexts: [],
                    hidden_contexts: [],
                    enabled: false,
                },
                '/api/environments/:team/default_release_conditions/': {
                    default_groups: [],
                    enabled: false,
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            name: 'disabled flag',
            featureFlag: buildFeatureFlag({ active: false, rolloutPercentage: 100 }),
            expectedText: 'This flag is currently disabled',
        },
        {
            name: 'zero rollout',
            featureFlag: buildFeatureFlag({ active: true, rolloutPercentage: 0 }),
            expectedText: 'This flag is currently set to 0% rollout on all release conditions',
        },
    ])('warns when updating variants for a $name', ({ featureFlag, expectedText }) => {
        renderSchedule(featureFlag, ScheduledChangeOperationType.UpdateVariants)

        expect(screen.getByText(new RegExp(expectedText))).toBeInTheDocument()
    })

    it.each([
        {
            name: 'another operation',
            featureFlag: buildFeatureFlag({ active: false, rolloutPercentage: 0 }),
            operation: ScheduledChangeOperationType.UpdateStatus,
        },
        {
            name: 'nonzero rollout',
            featureFlag: buildFeatureFlag({ active: true, rolloutPercentage: 1 }),
            operation: ScheduledChangeOperationType.UpdateVariants,
        },
        {
            name: 'implicit rollout',
            featureFlag: buildFeatureFlag({ active: true, rolloutPercentage: null }),
            operation: ScheduledChangeOperationType.UpdateVariants,
        },
        {
            name: 'non-multivariate flag',
            featureFlag: {
                ...buildFeatureFlag({ active: false, rolloutPercentage: 0 }),
                filters: { ...NEW_FLAG.filters, multivariate: null },
            },
            operation: ScheduledChangeOperationType.UpdateVariants,
        },
    ])('does not warn for $name', ({ featureFlag, operation }) => {
        renderSchedule(featureFlag, operation)

        expect(screen.queryByText(/Updating variants alone won't make the rollout go live/)).not.toBeInTheDocument()
    })
})
