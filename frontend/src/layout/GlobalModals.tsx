import { actions, kea, path, reducers, useActions, useValues } from 'kea'

import { ItemSelectModal } from 'lib/components/FileSystem/ItemSelectModal/ItemSelectModal'
import { LinkToModal } from 'lib/components/FileSystem/LinkTo/LinkTo'
import { MoveToModal } from 'lib/components/FileSystem/MoveTo/MoveTo'
import { HedgehogBuddyWithLogic } from 'lib/components/HedgehogBuddy/HedgehogBuddyWithLogic'
import { SuperpowersModal } from 'lib/components/Superpowers/Superpowers'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { TimeSensitiveAuthenticationModal } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { GlobalCustomUnitModal } from 'lib/components/UnitPicker/GlobalCustomUnitModal'
import { UpgradeModal } from 'lib/components/UpgradeModal/UpgradeModal'
import { TwoFactorSetupModal } from 'scenes/authentication/TwoFactorSetupModal'
import { PaymentEntryModal } from 'scenes/billing/PaymentEntryModal'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
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
    const { superpowersEnabled } = useValues(superpowersLogic)

    return (
        <>
            <InviteModal isOpen={isInviteModalShown} onClose={hideInviteModal} />
            <CreateOrganizationModal isVisible={isCreateOrganizationModalShown} onClose={hideCreateOrganizationModal} />
            <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
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
            {superpowersEnabled && <SuperpowersModal />}
        </>
    )
}
