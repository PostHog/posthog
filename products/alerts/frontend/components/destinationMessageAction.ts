import { LemonDialog } from '@posthog/lemon-ui'

import type { AlertNotificationDestinationMessageAction } from './AlertNotificationDestinationEditor'

export interface DestinationMessageActionProps {
    messageCustomized: boolean
    loading: boolean
    onCustomize: () => void
    onReset: () => void
}

/** "Customize" on a destination with the standard message, or "Reset to standard message" on an edited one. */
export function destinationMessageAction({
    messageCustomized,
    loading,
    onCustomize,
    onReset,
}: DestinationMessageActionProps): AlertNotificationDestinationMessageAction {
    if (!messageCustomized) {
        return {
            label: 'Customize',
            tooltip: 'Edit the message this destination sends',
            onClick: onCustomize,
            loading,
            dataAttr: 'alert-destination-customize-message',
        }
    }
    return {
        label: 'Reset to standard message',
        tooltip: 'Send the standard PostHog message instead of your edited one',
        onClick: () =>
            LemonDialog.open({
                title: 'Reset to the standard message?',
                description:
                    "This destination will send PostHog's standard message. Your edits to its message are deleted.",
                primaryButton: {
                    children: 'Reset',
                    status: 'danger',
                    onClick: onReset,
                    'data-attr': 'alert-destination-reset-message-confirm',
                },
                secondaryButton: { children: 'Cancel' },
            }),
        loading,
        dataAttr: 'alert-destination-reset-message',
    }
}
