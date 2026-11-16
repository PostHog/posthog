import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import type { OrganizationPersonalAPIKeyApi } from 'products/platform_features/frontend/generated/api.schemas'

import type { KeyAction, KeyActionTarget } from './organizationPersonalAPIKeysLogic'

function confirmOnce(onConfirm: () => void): () => void {
    let confirmed = false
    return () => {
        if (!confirmed) {
            // The button remains mounted during the dialog's close animation.
            confirmed = true
            onConfirm()
        }
    }
}

function captureDialogOpened(action: KeyAction, target: KeyActionTarget): void {
    posthog.capture('organization personal api key action dialog opened', { action, target })
}

function keyName(key: OrganizationPersonalAPIKeyApi, owner: string): JSX.Element {
    return (
        <>
            The key <span className="font-mono">{key.mask_value}</span> owned by <strong>{owner}</strong>
        </>
    )
}

export function openRollKeyDialog(key: OrganizationPersonalAPIKeyApi, owner: string, onConfirm: () => void): void {
    captureDialogOpened('roll', 'single')
    LemonDialog.open({
        maxWidth: 480,
        title: 'Roll personal API key?',
        description: (
            <>
                <p>
                    {keyName(key, owner)} gets a new secret that is not shown to anyone. It keeps its scopes and
                    settings, but stops working until the owner rolls it again in their own settings.
                </p>
                {key.reaches_other_organizations ? (
                    <p>This key also works in other organizations, so it stops working there too.</p>
                ) : null}
                <p>The owner gets an email about this change.</p>
            </>
        ),
        primaryButton: {
            children: 'Roll key',
            status: 'danger',
            onClick: confirmOnce(onConfirm),
            'data-attr': 'organization-personal-api-key-roll-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export function openRevokeKeyDialog(key: OrganizationPersonalAPIKeyApi, owner: string, onConfirm: () => void): void {
    captureDialogOpened('revoke', 'single')
    LemonDialog.open({
        maxWidth: 480,
        title: 'Revoke this personal API key?',
        description: (
            <>
                <p>
                    <strong>{owner}</strong>'s key <span className="font-mono">{key.mask_value}</span> will be deleted.
                    Any integration or script that uses it will stop working right away. You can't undo this.
                </p>
                {key.reaches_other_organizations ? (
                    <p>The key also works in other organizations {owner} belongs to. It will stop working there too.</p>
                ) : null}
                <p>We'll email {owner} about this change.</p>
            </>
        ),
        primaryButton: {
            children: 'Revoke key',
            status: 'danger',
            onClick: confirmOnce(onConfirm),
            'data-attr': 'organization-personal-api-key-revoke-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}
