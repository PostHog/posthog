import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ExperimentExposureCriteria, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'

import { ExposureCriteriaPanel } from './ExposureCriteriaPanel'

jest.mock('lib/components/TestAccountFiltersSwitch', () => ({ TestAccountFilterSwitch: () => null }))

describe('ExposureCriteriaPanel', () => {
    const WAREHOUSE_NATIVE_OPTION = '[data-attr="experiment-wizard-exposure-warehouse-native"]'

    const renderPanel = (
        onChange: jest.Mock,
        metricDataSources = { warehouseNative: false, posthog: false },
        exposureCriteria: ExperimentExposureCriteria = NEW_EXPERIMENT.exposure_criteria as ExperimentExposureCriteria
    ): void => {
        render(
            <ExposureCriteriaPanel
                experiment={{ ...NEW_EXPERIMENT, exposure_criteria: exposureCriteria } as Experiment}
                featureFlag={null}
                onChange={onChange}
                metricDataSources={metricDataSources}
                compact
            />
        )
    }

    const openExposureSelect = async (): Promise<void> => {
        await userEvent.click(screen.getByText('Feature flag is called'))
    }

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('hides the warehouse-native exposure while the project is not flagged in', async () => {
        renderPanel(jest.fn())

        await openExposureSelect()

        expect(screen.getByText('Custom event')).toBeInTheDocument()
        expect(document.querySelector(WAREHOUSE_NATIVE_OPTION)).not.toBeInTheDocument()
    })

    it.each([
        ['starts an empty warehouse-native exposure when the draft has no metrics', false, 1],
        ['blocks the warehouse-native exposure while the draft has PostHog metrics', true, 0],
    ])('%s', async (_, hasPosthogMetrics, expectedChanges) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.BIGQUERY_DIRECT_QUERY]: true })
        const onChange = jest.fn()
        renderPanel(onChange, { warehouseNative: false, posthog: hasPosthogMetrics })

        await openExposureSelect()
        await userEvent.click(document.querySelector(WAREHOUSE_NATIVE_OPTION)!)

        expect(onChange).toHaveBeenCalledTimes(expectedChanges)
        if (expectedChanges) {
            expect(onChange).toHaveBeenCalledWith({
                exposure_config: {
                    kind: NodeKind.ExperimentWarehouseNativeExposureConfig,
                    connection_id: '',
                    unit: { unit_type: '', id_namespace: '' },
                    query: '',
                },
                activation_config: undefined,
            })
        }
    })

    it.each([
        ['explains that a custom $feature_flag_called exposure counts as the default', '$feature_flag_called', true],
        ['shows no default-event note for a custom event', '$pageview', false],
    ])('%s', (_, event, showsNote) => {
        renderPanel(jest.fn(), undefined, {
            ...NEW_EXPERIMENT.exposure_criteria,
            exposure_config: { kind: NodeKind.ExperimentEventExposureConfig, event, properties: [] },
        })

        expect(!!document.querySelector('[data-attr="experiment-exposure-default-event-note"]')).toBe(showsNote)
    })
})
