import { LemonDialog } from '@posthog/lemon-ui'

export function openDeleteConversationDialog(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Delete chat?',
        description: 'The chat will be removed from your history.',
        primaryButton: {
            children: 'Delete',
            status: 'danger',
            onClick: onConfirm,
        },
        secondaryButton: { children: 'Cancel' },
    })
}
