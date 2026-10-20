import { LemonDialog } from '@posthog/lemon-ui'

import { LaunchValidationContent } from './components/LaunchValidationContent'
import { LaunchValidationIssue } from './productTourLogic'

export function productTourDialogHandlers({
    launchValidationIssues,
    editingProductTour,
    launchProductTour,
    stopProductTour,
    resumeProductTour,
}: {
    launchValidationIssues: LaunchValidationIssue[]
    editingProductTour: (editing: boolean) => void
    launchProductTour: () => void
    stopProductTour: () => void
    resumeProductTour: () => void
}): {
    handleLaunch: () => void
    handleStop: () => void
    handleResume: () => void
} {
    const handleLaunch = (): void => {
        if (launchValidationIssues.length > 0) {
            LemonDialog.open({
                title: 'Tour not ready to launch',
                content: <LaunchValidationContent issues={launchValidationIssues} />,
                maxWidth: 600,
                primaryButton: {
                    children: 'Edit tour',
                    type: 'secondary',
                    onClick: () => editingProductTour(true),
                    size: 'small',
                },
                secondaryButton: {
                    children: 'Cancel',
                    type: 'tertiary',
                    size: 'small',
                },
            })
            return
        }
        LemonDialog.open({
            title: 'Launch this product tour?',
            content: (
                <div className="text-sm text-secondary">
                    The tour will immediately start displaying to users matching the display conditions.
                </div>
            ),
            primaryButton: {
                children: 'Launch',
                type: 'primary',
                onClick: launchProductTour,
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const handleStop = (): void => {
        LemonDialog.open({
            title: 'Stop this product tour?',
            content: <div className="text-sm text-secondary">The tour will no longer be displayed to users.</div>,
            primaryButton: {
                children: 'Stop',
                type: 'primary',
                onClick: stopProductTour,
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const handleResume = (): void => {
        LemonDialog.open({
            title: 'Resume this product tour?',
            content: (
                <div className="text-sm text-secondary">
                    Once resumed, the tour will be visible to your users again.
                </div>
            ),
            primaryButton: {
                children: 'Resume',
                type: 'primary',
                onClick: resumeProductTour,
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    return { handleLaunch, handleStop, handleResume }
}
