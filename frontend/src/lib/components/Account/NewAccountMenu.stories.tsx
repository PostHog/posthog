import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { UpgradeModal } from 'lib/components/UpgradeModal/UpgradeModal'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { userLogic } from 'scenes/userLogic'

import { globalModalsLogic } from '~/layout/globalModalsLogic'
import { PanelLayout } from '~/layout/panel-layout/PanelLayout'
import { useStorybookMocks } from '~/mocks/browser'
import preflight from '~/mocks/fixtures/_preflight.json'
import { AvailableFeature, PreflightStatus } from '~/types'

function MobileProjectCreation({ projectLimit }: { projectLimit: number }): JSX.Element {
    const organization = {
        ...MOCK_DEFAULT_ORGANIZATION,
        name: 'Example organization',
        available_product_features: [
            { key: AvailableFeature.ORGANIZATIONS_PROJECTS, name: 'Projects', limit: projectLimit },
        ],
    }
    useStorybookMocks({
        get: {
            '/api/organizations/@current/': () => [200, organization],
            '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, organization, pending_invites: [] }],
            '/_preflight/': () => [200, { ...preflight, cloud: true, can_create_org: true }],
        },
    })
    const { isCreateProjectModalShown } = useValues(globalModalsLogic)
    const { user, userLoading } = useValues(userLogic)
    const { preflight: loadedPreflight, preflightLoading } = useValues(preflightLogic)
    const { loadUserSuccess } = useActions(userLogic)
    const { hideCreateProjectModal } = useActions(globalModalsLogic)
    const { loadPreflightSuccess } = useActions(preflightLogic)
    useEffect(() => {
        if (
            user &&
            !userLoading &&
            !user.organization?.available_product_features?.some(
                (feature) => feature.key === AvailableFeature.ORGANIZATIONS_PROJECTS && feature.limit === projectLimit
            )
        ) {
            loadUserSuccess({ ...MOCK_DEFAULT_USER, organization, pending_invites: [] })
        }
    }, [loadUserSuccess, user, userLoading, projectLimit])
    useEffect(() => {
        if (loadedPreflight && !preflightLoading && !loadedPreflight.can_create_org) {
            loadPreflightSuccess({
                ...preflight,
                cloud: true,
                can_create_org: true,
                slack_service: { available: false },
                data_warehouse_integrations: { hubspot: {}, salesforce: {} },
                wizard_cloud_run_available: false,
            } as PreflightStatus)
        }
    }, [loadPreflightSuccess, loadedPreflight, preflightLoading])
    return (
        <>
            {loadedPreflight?.cloud &&
                loadedPreflight.can_create_org &&
                user?.organization?.available_product_features?.some(
                    (feature) =>
                        feature.key === AvailableFeature.ORGANIZATIONS_PROJECTS && feature.limit === projectLimit
                ) && <span data-attr="project-creation-fixture-ready" />}
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
}
export default meta
type Story = StoryObj<typeof meta>
export const AtLimit: Story = { args: { projectLimit: 1 } }
export const BelowLimit: Story = { args: { projectLimit: 6 } }
