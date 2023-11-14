import { kea, path, actions, reducers, useActions, useValues } from 'kea'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'

import type { globalModalsLogicType } from './GlobalModalsType'
import { FeaturePreviewsModal } from './FeaturePreviews'
import { UpgradeModal } from 'scenes/UpgradeModal'
import { LemonModal } from '@posthog/lemon-ui'
import { Setup2FA } from 'scenes/authentication/Setup2FA'
import { userLogic } from 'scenes/userLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { Prompt } from 'lib/logic/newPrompt/Prompt'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { InviteModal } from 'scenes/settings/organization/InviteModal'

export const globalModalsLogic = kea<globalModalsLogicType>([
    path(['layout', 'navigation', 'globalModalsLogic']),
    actions({
        showCreateOrganizationModal: true,
        hideCreateOrganizationModal: true,
        showCreateProjectModal: true,
        hideCreateProjectModal: true,
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
    }),
])

export function GlobalModals(): JSX.Element {
    const { isCreateOrganizationModalShown, isCreateProjectModalShown } = useValues(globalModalsLogic)
    const { hideCreateOrganizationModal, hideCreateProjectModal } = useActions(globalModalsLogic)
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { user } = useValues(userLogic)

    return (
        <>
            <InviteModal isOpen={isInviteModalShown} onClose={hideInviteModal} />
            <CreateOrganizationModal isVisible={isCreateOrganizationModalShown} onClose={hideCreateOrganizationModal} />
            <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
            <FeaturePreviewsModal />
            <UpgradeModal />

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
                            membersLogic.actions.loadMembers()
                        }}
                    />
                </LemonModal>
            )}
            <FlaggedFeature flag="enable-prompts">
                <Prompt />
            </FlaggedFeature>
        </>
    )
}
