import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { AvailableFeature, Realm } from '~/types'

import { UpgradeModal } from './UpgradeModal'
import { upgradeModalLogic } from './upgradeModalLogic'

type StoryArgs = { feature: AvailableFeature }

const meta: Meta<StoryArgs> = {
    title: 'Components/Upgrade Modal',
    component: UpgradeModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-31 12:00:00',
    },
    render: ({ feature }) => {
        useStorybookMocks({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, is_debug: true, realm: Realm.Cloud },
                '/api/billing/': { ...billingJson },
            },
        })
        const { showUpgradeModal } = useActions(upgradeModalLogic)
        useEffect(() => {
            showUpgradeModal(feature)
        }, [feature, showUpgradeModal])

        return <UpgradeModal />
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const RoleBasedAccess: Story = {
    args: { feature: AvailableFeature.ROLE_BASED_ACCESS },
}
