import { actions, kea, path, reducers, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { ItemSelectModal } from 'lib/components/FileSystem/ItemSelectModal/ItemSelectModal'
import { LinkToModal } from 'lib/components/FileSystem/LinkTo/LinkTo'
import { MoveToModal } from 'lib/components/FileSystem/MoveTo/MoveTo'
import { HedgehogBuddyWithLogic } from 'lib/components/HedgehogBuddy/HedgehogBuddyWithLogic'
import { TimeSensitiveAuthenticationModal } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { GlobalCustomUnitModal } from 'lib/components/UnitPicker/GlobalCustomUnitModal'
import { UpgradeModal } from 'lib/components/UpgradeModal/UpgradeModal'
import { TwoFactorSetupModal } from 'scenes/authentication/TwoFactorSetupModal'
import { PaymentEntryModal } from 'scenes/billing/PaymentEntryModal'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { CreateEnvironmentModal } from 'scenes/project/CreateEnvironmentModal'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { EnvironmentRollbackModal } from 'scenes/settings/environment/EnvironmentRollbackModal'
import { environmentRollbackModalLogic } from 'scenes/settings/environment/environmentRollbackModalLogic'
import { InviteModal } from 'scenes/settings/organization/InviteModal'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { PreviewingCustomCssModal } from 'scenes/themes/PreviewingCustomCssModal'

import type { globalModalsLogicType } from './GlobalModalsType'

export const globalModalsLogic = kea<globalModalsLogicType>([
    path(['layout', 'navigation', 'globalModalsLogic']),
    actions({
        showCreateOrganizationModal: true,
        hideCreateOrganizationModal: true,
        showCreateProjectModal: true,
        hideCreateProjectModal: true,
        showCreateEnvironmentModal: true,
        hideCreateEnvironmentModal: true,
    }),
    reducers({
        isCreateOrganizationModalShown: [
            false,
            {
                showCreateOrganizationModal: () => true,
                hideCreateOrganizationModal: () => false,
            },
        ],
        isCreateProjectModalShown: [
            false,
            {
                showCreateProjectModal: () => true,
                hideCreateProjectModal: () => false,
            },
        ],
        isCreateEnvironmentModalShown: [
            false,
            {
                showCreateEnvironmentModal: () => true,
                hideCreateEnvironmentModal: () => false,
            },
        ],
    }),
])

export function GlobalModals(): JSX.Element {
    const { isCreateOrganizationModalShown, isCreateProjectModalShown, isCreateEnvironmentModalShown } =
        useValues(globalModalsLogic)
    const {
        hideCreateOrganizationModal,
        hideCreateProjectModal,
        hideCreateEnvironmentModal,
        showCreateEnvironmentModal,
    } = useActions(globalModalsLogic)
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { hasEnvironmentsRollbackFeature } = useValues(environmentRollbackModalLogic)

    // Expose modal actions to window for debugging purposes
    useEffect(() => {
        const isDebugEnabled = typeof window !== 'undefined' && window.localStorage?.getItem('ph-debug') === 'true'

        if (typeof window !== 'undefined' && isDebugEnabled) {
            // @ts-expect-error-next-line
            window.posthogDebug = window.posthogDebug || {}
            // @ts-expect-error-next-line
            window.posthogDebug.showCreateEnvironmentModal = showCreateEnvironmentModal
        }

        return () => {
            if (typeof window !== 'undefined') {
                // @ts-expect-error-next-line
                if (window.posthogDebug) {
                    // @ts-expect-error-next-line
                    delete window.posthogDebug.showCreateEnvironmentModal
                }
            }
        }
    }, [showCreateEnvironmentModal])

    return (
        <>
            <InviteModal isOpen={isInviteModalShown} onClose={hideInviteModal} />
            <CreateOrganizationModal isVisible={isCreateOrganizationModalShown} onClose={hideCreateOrganizationModal} />
            <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
            <CreateEnvironmentModal isVisible={isCreateEnvironmentModalShown} onClose={hideCreateEnvironmentModal} />
            <UpgradeModal />
            <TimeSensitiveAuthenticationModal />
            <SessionPlayerModal />
            <PreviewingCustomCssModal />
            <TwoFactorSetupModal />
            <HedgehogBuddyWithLogic />
            <PaymentEntryModal />
            <GlobalCustomUnitModal />
            <MoveToModal />
            <LinkToModal />
            <ItemSelectModal />
            {hasEnvironmentsRollbackFeature && <EnvironmentRollbackModal />}
        </>
    )
}
