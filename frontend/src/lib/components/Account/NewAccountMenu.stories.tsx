import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { UpgradeModal } from 'lib/components/UpgradeModal/UpgradeModal'
import { getAppContext } from 'lib/utils/getAppContext'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'

import { globalModalsLogic } from '~/layout/globalModalsLogic'
import { PanelLayout } from '~/layout/panel-layout/PanelLayout'
import preflight from '~/mocks/fixtures/_preflight.json'
import { AvailableFeature, OrganizationType, PreflightStatus } from '~/types'

function organizationWithProjectLimit(projectLimit: number): OrganizationType {
    return {
        ...MOCK_DEFAULT_ORGANIZATION,
        name: 'Example organization',
        available_product_features: [
            { key: AvailableFeature.ORGANIZATIONS_PROJECTS, name: 'Projects', limit: projectLimit },
        ],
    }
}

function MobileProjectCreation({
    restoreAppContext,
}: {
    projectLimit: number
    restoreAppContext?: () => void
}): JSX.Element {
    const { isCreateProjectModalShown } = useValues(globalModalsLogic)
    const { hideCreateProjectModal } = useActions(globalModalsLogic)
    useEffect(() => {
        restoreAppContext?.()
    }, [restoreAppContext])
    return (
        <>
            <span data-attr="project-creation-fixture-ready" />
            <PanelLayout />
            <UpgradeModal />
            <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
        </>
    )
}

const meta: Meta<typeof MobileProjectCreation> = {
    title: 'Layout/Mobile project creation',
    component: MobileProjectCreation,
    tags: ['test-skip-chromium'],
    parameters: { layout: 'fullscreen' },
    loaders: [
        ({ args }) => {
            const context = getAppContext()
            if (!context) {
                throw new Error('Project creation stories require an app context')
            }
            const previousUser = context.current_user
            const previousPreflight = context.preflight
            const organization = organizationWithProjectLimit(args.projectLimit)
            context.current_user = { ...MOCK_DEFAULT_USER, organization, pending_invites: [] }
            context.preflight = {
                ...preflight,
                cloud: true,
                can_create_org: true,
                slack_service: { available: false },
                data_warehouse_integrations: { hubspot: {}, salesforce: {} },
                wizard_cloud_run_available: false,
            } as PreflightStatus
            return {
                restoreAppContext: () => {
                    context.current_user = previousUser
                    context.preflight = previousPreflight
                },
            }
        },
    ],
    render: (args, { loaded }) => <MobileProjectCreation {...args} restoreAppContext={loaded.restoreAppContext} />,
}
export default meta
type Story = StoryObj<typeof meta>
export const AtLimit: Story = { args: { projectLimit: 1 } }
export const BelowLimit: Story = { args: { projectLimit: 6 } }
