import { Meta, StoryObj } from '@storybook/react'

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
                description="Your impersonation session has expired. Provide a reason to continue impersonating this user, or end the session."
                confirmText="Re-impersonate"
                closable={false}
                cancelButton={{ label: 'End impersonation', status: 'danger', onClick: noop }}
                inline
            />
        </ModalShell>
    ),
}

export const StandardReason: Story = {
    render: () => (
        <ModalShell>
            <ImpersonationReasonModal
                isOpen
                onClose={noop}
                onConfirm={noop}
                title="Impersonate user"
                description="Provide a reason for impersonating this user."
                confirmText="Impersonate"
                inline
            />
        </ModalShell>
    ),
}

export const Loading: Story = {
    render: () => (
        <ModalShell>
            <ImpersonationReasonModal
                isOpen
                onClose={noop}
                onConfirm={noop}
                title="Impersonate user"
                description="Provide a reason for impersonating this user."
                confirmText="Impersonate"
                loading
                inline
            />
        </ModalShell>
    ),
}
