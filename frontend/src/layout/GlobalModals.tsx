import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { ItemSelectModal } from 'lib/components/FileSystem/ItemSelectModal/ItemSelectModal'
import { LinkToModal } from 'lib/components/FileSystem/LinkTo/LinkTo'
import { MoveToModal } from 'lib/components/FileSystem/MoveTo/MoveTo'
import { HedgehogMode } from 'lib/components/HedgehogMode/HedgehogMode'
import { MaybeProductPushWelcome } from 'lib/components/NavPanelAdvertisement/MaybeProductPushWelcome'
import { SuperpowersModal } from 'lib/components/Superpowers/Superpowers'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { TimeSensitiveAuthenticationModal } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { GlobalCustomUnitModal } from 'lib/components/UnitPicker/GlobalCustomUnitModal'
import { UpgradeModal } from 'lib/components/UpgradeModal/UpgradeModal'
import { traceDialogOpenLogic } from 'lib/components/ViewTraceButton/traceDialogOpenLogic'
import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { inviteLogic } from 'lib/logic/inviteLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { productGlobalModals } from '~/productGlobalModals'

import { globalModalsLogic } from './globalModalsLogic'

// Modals that no product owns. A product adds its modal through `globalModals` in its manifest.
const InviteModal = lazyWithRetry(() =>
    import('scenes/settings/organization/InviteModal').then((m) => ({ default: m.InviteModal }))
)
const CreateOrganizationModal = lazyWithRetry(() =>
    import('scenes/organization/CreateOrganizationModal').then((m) => ({ default: m.CreateOrganizationModal }))
)
const CreateProjectModal = lazyWithRetry(() =>
    import('scenes/project/CreateProjectModal').then((m) => ({ default: m.CreateProjectModal }))
)
const PreviewingCustomCssModal = lazyWithRetry(() =>
    import('scenes/themes/PreviewingCustomCssModal').then((m) => ({ default: m.PreviewingCustomCssModal }))
)
const TwoFactorSetupModal = lazyWithRetry(() =>
    import('scenes/authentication/two-factor-setup/TwoFactorSetupModal').then((m) => ({
        default: m.TwoFactorSetupModal,
    }))
)
const PaymentEntryModal = lazyWithRetry(() =>
    import('scenes/billing/PaymentEntryModal').then((m) => ({ default: m.PaymentEntryModal }))
)
const MaybeWelcomeDialog = lazyWithRetry(() =>
    import('scenes/welcome/WelcomeDialog').then((m) => ({ default: m.MaybeWelcomeDialog }))
)

const productModals = Object.entries(productGlobalModals).map(
    ([key, load]) => [key, lazyWithRetry(() => load().then((component) => ({ default: component })))] as const
)

const TraceDialog = lazyWithRetry(() =>
    import('products/tracing/frontend/components/TraceDialog/TraceDialog').then((m) => ({
        default: m.TraceDialog,
    }))
)

const MaybePhaiOnboarding = lazyWithRetry(() =>
    import('scenes/max/components/MaybePhaiOnboarding').then((m) => ({
        default: m.MaybePhaiOnboarding,
    }))
)

export function GlobalModals(): JSX.Element {
    const { isCreateOrganizationModalShown, isCreateProjectModalShown } = useValues(globalModalsLogic)
    const { hideCreateOrganizationModal, hideCreateProjectModal } = useActions(globalModalsLogic)
    const { isOpen: isTraceDialogOpen } = useValues(traceDialogOpenLogic)
    // Grace-extended so the dialog's exit animation finishes before the lazy subtree unmounts.
    const shouldRenderTraceDialog = useKeepMountedWhileOpen(isTraceDialogOpen)
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { superpowersEnabled } = useValues(superpowersLogic)

    return (
        <>
            <Suspense fallback={null}>
                <InviteModal isOpen={isInviteModalShown} onClose={hideInviteModal} />
                <CreateOrganizationModal
                    isVisible={isCreateOrganizationModalShown}
                    onClose={hideCreateOrganizationModal}
                />
                <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
                <PreviewingCustomCssModal />
                <TwoFactorSetupModal />
                <PaymentEntryModal />
                <MaybeWelcomeDialog />
                {productModals.map(([key, ProductModal]) => (
                    <ProductModal key={key} />
                ))}
            </Suspense>
            <UpgradeModal />
            <TimeSensitiveAuthenticationModal />
            {shouldRenderTraceDialog ? (
                <Suspense fallback={null}>
                    <TraceDialog />
                </Suspense>
            ) : null}
            <HedgehogMode />
            <GlobalCustomUnitModal />
            <MoveToModal />
            <LinkToModal />
            <ItemSelectModal />
            {superpowersEnabled && <SuperpowersModal />}
            <MaybeProductPushWelcome />
            <Suspense fallback={null}>
                <MaybePhaiOnboarding />
            </Suspense>
        </>
    )
}
