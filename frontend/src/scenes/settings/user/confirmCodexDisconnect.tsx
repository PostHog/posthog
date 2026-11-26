import { LemonDialog } from '@posthog/lemon-ui'

export function confirmCodexDisconnect(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Disconnect Codex?',
        description: (
            <p>
                PostHog removes your ChatGPT sign-in. Codex cloud tasks that use your ChatGPT plan stop working until
                you connect again.
            </p>
        ),
        primaryButton: {
            children: 'Disconnect',
            status: 'danger',
            onClick: () => onConfirm(),
        },
        secondaryButton: { children: 'Cancel' },
    })
}
