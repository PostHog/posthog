import { Meta, StoryObj } from '@storybook/react'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { ImpersonationReasonModal } from './ImpersonationReasonModal'

const meta: Meta<typeof ImpersonationReasonModal> = {
    title: 'Layout/Impersonation Reason Modal',
    component: ImpersonationReasonModal,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta
type Story = StoryObj<typeof ImpersonationReasonModal>

const noop = (): void => {}

const IMPERSONATED_EMAIL = 'customer@example.com'

function ModalShell({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="bg-default p-4">{children}</div>
}

export const SessionExpiredReImpersonation: Story = {
    render: () => (
        <ModalShell>
            <ImpersonationReasonModal
                isOpen
                onConfirm={noop}
                title="Impersonation session expired"
                description={`Your session impersonating ${IMPERSONATED_EMAIL} has expired.`}
                confirmText="Re-impersonate"
                closable={false}
                cancelButton={{ label: 'Return to admin', status: 'danger', onClick: noop }}
                inline
            >
                <LemonCheckbox checked onChange={noop} label="Read-only mode (recommended)" />
            </ImpersonationReasonModal>
        </ModalShell>
    ),
}

export const UpgradeToReadWrite: Story = {
    render: () => (
        <ModalShell>
            <ImpersonationReasonModal
                isOpen
                onClose={noop}
                onConfirm={noop}
                title="Upgrade to read-write impersonation"
                description="Read-write mode allows you to make changes on behalf of the user. Please provide a reason for this upgrade."
                confirmText="Upgrade"
                inline
            />
        </ModalShell>
    ),
}

export const Loading: Story = {
    parameters: {
        // The primary button spins while loading — don't wait for it to disappear.
        testOptions: { waitForLoadersToDisappear: false },
    },
    render: () => (
        <ModalShell>
            <ImpersonationReasonModal
                isOpen
                onClose={noop}
                onConfirm={noop}
                title="Upgrade to read-write impersonation"
                description="Read-write mode allows you to make changes on behalf of the user. Please provide a reason for this upgrade."
                confirmText="Upgrade"
                loading
                inline
            />
        </ModalShell>
    ),
}
