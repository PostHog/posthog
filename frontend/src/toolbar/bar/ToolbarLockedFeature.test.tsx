import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ToolbarLockedFeature } from '~/toolbar/bar/ToolbarLockedFeature'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarEntitlementsLogic } from '~/toolbar/toolbarEntitlementsLogic'

describe('ToolbarLockedFeature', () => {
    beforeEach(() => {
        initKeaTests()
        toolbarConfigLogic.build({ apiURL: 'http://localhost' }).mount()
        useMocks({ get: { '/api/user/toolbar_entitlements': () => ({ entitlements: { toolbar_heatmaps: true } }) } })
    })

    it('rechecks the plan so an upgrade in another tab unlocks the feature', async () => {
        const logic = toolbarEntitlementsLogic()
        logic.mount()
        render(<ToolbarLockedFeature featureName="Heatmaps" />)

        await expectLogic(logic, () => {
            fireEvent.click(screen.getByText('Check again'))
        })
            .toDispatchActions(['loadEntitlements', 'loadEntitlementsSuccess'])
            .toMatchValues({ entitlements: { toolbar_heatmaps: true } })
    })
})
