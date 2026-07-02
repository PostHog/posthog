import { useActions, useValues } from 'kea'
import { Suspense, lazy } from 'react'

import { ItemSelectModal } from 'lib/components/FileSystem/ItemSelectModal/ItemSelectModal'
import { LinkToModal } from 'lib/components/FileSystem/LinkTo/LinkTo'
import { MoveToModal } from 'lib/components/FileSystem/MoveTo/MoveTo'
import { HedgehogMode } from 'lib/components/HedgehogMode/HedgehogMode'
import { SuperpowersModal } from 'lib/components/Superpowers/Superpowers'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { TimeSensitiveAuthenticationModal } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { GlobalCustomUnitModal } from 'lib/components/UnitPicker/GlobalCustomUnitModal'
import { UpgradeModal } from 'lib/components/UpgradeModal/UpgradeModal'
import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { TwoFactorSetupModal } from 'scenes/authentication/two-factor-setup/TwoFactorSetupModal'
import { PaymentEntryModal } from 'scenes/billing/PaymentEntryModal'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { InviteModal } from 'scenes/settings/organization/InviteModal'
import { PreviewingCustomCssModal } from 'scenes/themes/PreviewingCustomCssModal'
import { MaybeWelcomeDialog } from 'scenes/welcome/WelcomeDialog'

import { ComposeTicketModal } from 'products/conversations/frontend/components/ComposeTicket'
import { logsViewerModalLogic } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal/logsViewerModalLogic'

import { globalModalsLogic } from './globalModalsLogic'
import { navigationLogic } from './navigation-3000/navigationLogic'
import { ConfigureHomeModal } from './scenes/ConfigureHomeModal'

// The session player modal anchors the entire replay player graph; loading it only when a
// recording is opened keeps that graph out of the chunk every logged-in page downloads.
const SessionPlayerModal = lazy(() =>
    import('scenes/session-recordings/player/modal/SessionPlayerModal').then((m) => ({
        default: m.SessionPlayerModal,
    }))
)

// Same trick for the logs viewer, whose sparkline anchors chart.js.
const LogsViewerModal = lazy(() =>
    import('products/logs/frontend/components/LogsViewer/LogsViewerModal').then((m) => ({
        default: m.LogsViewerModal,
    }))
)

export function GlobalModals(): JSX.Element {
    const { isCreateOrganizationModalShown, isCreateProjectModalShown } = useValues(globalModalsLogic)
    const { hideCreateOrganizationModal, hideCreateProjectModal } = useActions(globalModalsLogic)
    const { activeSessionRecording } = useValues(sessionPlayerModalLogic)
    const { isOpen: isLogsViewerModalOpen } = useValues(logsViewerModalLogic)
    // Grace-extended so the modals' exit animations finish before the lazy subtree unmounts.
    const shouldRenderSessionPlayerModal = useKeepMountedWhileOpen(!!activeSessionRecording)
    const shouldRenderLogsViewerModal = useKeepMountedWhileOpen(isLogsViewerModalOpen)
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { superpowersEnabled } = useValues(superpowersLogic)
    const { isConfigureHomeModalOpen } = useValues(navigationLogic)
    const { hideConfigureHomeModal } = useActions(navigationLogic)

    return (
        <>
            <InviteModal isOpen={isInviteModalShown} onClose={hideInviteModal} />
            <CreateOrganizationModal isVisible={isCreateOrganizationModalShown} onClose={hideCreateOrganizationModal} />
            <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
            <UpgradeModal />
            <TimeSensitiveAuthenticationModal />
            {shouldRenderSessionPlayerModal ? (
                <Suspense fallback={null}>
                    <SessionPlayerModal />
                </Suspense>
            ) : null}
            {shouldRenderLogsViewerModal ? (
                <Suspense fallback={null}>
                    <LogsViewerModal />
                </Suspense>
            ) : null}
            <PreviewingCustomCssModal />
            <TwoFactorSetupModal />
            <HedgehogMode />
            <PaymentEntryModal />
            <GlobalCustomUnitModal />
            <MoveToModal />
            <LinkToModal />
            <ItemSelectModal />
            {superpowersEnabled && <SuperpowersModal />}
            <ConfigureHomeModal isOpen={isConfigureHomeModalOpen} onClose={hideConfigureHomeModal} />
            <MaybeWelcomeDialog />
            <ComposeTicketModal />
        </>
    )
}
