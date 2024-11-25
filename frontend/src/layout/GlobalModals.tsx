import { LemonModal } from '@posthog/lemon-ui'
import { actions, kea, path, reducers, useActions, useValues } from 'kea'
import { ConfirmUpgradeModal } from 'lib/components/ConfirmUpgradeModal/ConfirmUpgradeModal'
import { HedgehogBuddyWithLogic } from 'lib/components/HedgehogBuddy/HedgehogBuddyWithLogic'
import { TimeSensitiveAuthenticationModal } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { UpgradeModal } from 'lib/components/UpgradeModal/UpgradeModal'
import { Setup2FA } from 'scenes/authentication/Setup2FA'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { membersLogic } from 'scenes/organization/membersLogic'
import { CreateEnvironmentModal } from 'scenes/project/CreateEnvironmentModal'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { InviteModal } from 'scenes/settings/organization/InviteModal'
import { PreviewingCustomCssModal } from 'scenes/themes/PreviewingCustomCssModal'
import { userLogic } from 'scenes/userLogic'

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
    const { hideCreateOrganizationModal, hideCreateProjectModal, hideCreateEnvironmentModal } =
        useActions(globalModalsLogic)
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { user } = useValues(userLogic)

    return (
        <>
            <InviteModal isOpen={isInviteModalShown} onClose={hideInviteModal} />
            <CreateOrganizationModal isVisible={isCreateOrganizationModalShown} onClose={hideCreateOrganizationModal} />
            <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
            <CreateEnvironmentModal isVisible={isCreateEnvironmentModalShown} onClose={hideCreateEnvironmentModal} />
            <UpgradeModal />
            <ConfirmUpgradeModal />
            <TimeSensitiveAuthenticationModal />
            <SessionPlayerModal />
            <PreviewingCustomCssModal />
            {user && user.organization?.enforce_2fa && !user.is_2fa_enabled && (
                <LemonModal title="Set up 2FA" closable={false}>
                    <p>
                        <b>Your organization requires you to set up 2FA.</b>
                    </p>
                    <p>
                        <b>
                            Use an authenticator app like Google Authenticator or 1Password to scan the QR code below.
                        </b>
                    </p>
                    <Setup2FA
                        onSuccess={() => {
                            userLogic.actions.loadUser()
                            membersLogic.actions.loadAllMembers()
                        }}
                    />
                </LemonModal>
            )}
            <HedgehogBuddyWithLogic />
        </>
    )
}
