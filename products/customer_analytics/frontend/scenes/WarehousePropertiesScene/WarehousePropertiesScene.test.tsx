import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { WarehousePropertiesScene } from './WarehousePropertiesScene'

jest.mock('../CustomerAnalyticsConfigurationScene/account/WarehousePersonPropertiesSetting', () => ({
    WarehousePersonPropertiesSetting: () => <div>Person warehouse property settings</div>,
    WarehouseGroupPropertiesSetting: () => <div>Group warehouse property settings</div>,
}))

describe('WarehousePropertiesScene', () => {
    let unmountFeatureFlagLogic: () => void

    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
        unmountFeatureFlagLogic = featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
        unmountFeatureFlagLogic()
        window.localStorage.clear()
    })

    it('returns Not Found when the feature flag is disabled', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES]: false })

        render(<WarehousePropertiesScene />)

        expect(screen.getByText("Warehouse properties isn't available for this project yet.")).toBeInTheDocument()
        expect(screen.queryByText('Person warehouse property settings')).not.toBeInTheDocument()
    })

    it('allows direct access when the persisted feature flag is enabled', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES]: true })

        render(<WarehousePropertiesScene />)

        expect(screen.queryByText("Warehouse properties isn't available for this project yet.")).not.toBeInTheDocument()
        expect(screen.getByText('Person warehouse property settings')).toBeInTheDocument()
    })
})
