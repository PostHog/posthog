import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ToolbarLockedFeature } from '~/toolbar/floating/components/bar/ToolbarLockedFeature'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'
import { toolbarEntitlementsLogic } from '~/toolbar/shared/toolbarEntitlementsLogic'

const ENTITLEMENTS_URL = '/api/projects/2/toolbar/entitlements/'

describe('ToolbarLockedFeature', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({ get: { [ENTITLEMENTS_URL]: () => ({ entitlements: { toolbar_heatmaps: false } }) } })
        toolbarConfigLogic
            .build({ apiURL: 'http://localhost', accessToken: 'test-token', teamId: 2, projectId: 1 })
            .mount()
    })

    it('rechecks the plan so an upgrade in another tab unlocks the feature', async () => {
        const logic = toolbarEntitlementsLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadEntitlementsSuccess'])
            .toMatchValues({ entitlements: { toolbar_heatmaps: false } })

        render(<ToolbarLockedFeature featureName="Heatmaps" />)
        useMocks({ get: { [ENTITLEMENTS_URL]: () => ({ entitlements: { toolbar_heatmaps: true } }) } })

        await expectLogic(logic, () => {
            fireEvent.click(screen.getByText('Check again'))
        })
            .toDispatchActions(['loadEntitlements', 'loadEntitlementsSuccess'])
            .toMatchValues({ entitlements: { toolbar_heatmaps: true } })
    })
})
