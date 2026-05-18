import { LemonDialog } from '@posthog/lemon-ui'

import { Deployment } from '../fixtures'

/**
 * Shared confirm dialogs for the Redeploy / Rollback flow. Used from
 * both the deployment detail scene and the per-row More menu on the
 * project scene — keeping the copy in one place avoids drift when the
 * wording or button styling needs to change.
 */

export function openRedeployDialog(target: Deployment, onConfirm: (id: string) => void): void {
    LemonDialog.open({
        title: 'Redeploy?',
        description: `This will start a new deployment based on ${
            target.commit_sha || target.id
        }. It will run through the build pipeline before becoming current.`,
        primaryButton: {
            children: 'Redeploy',
            type: 'primary',
            onClick: () => onConfirm(target.id),
        },
        secondaryButton: { children: 'Cancel', type: 'secondary' },
    })
}

export function openRollbackDialog(target: Deployment, onConfirm: (id: string) => void): void {
    LemonDialog.open({
        title: 'Roll back to this deployment?',
        description: `This will immediately make ${target.commit_message || target.id} current.`,
        primaryButton: {
            children: 'Roll back',
            type: 'primary',
            status: 'danger',
            onClick: () => onConfirm(target.id),
        },
        secondaryButton: { children: 'Cancel', type: 'secondary' },
    })
}
