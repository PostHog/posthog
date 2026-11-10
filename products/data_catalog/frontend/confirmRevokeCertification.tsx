import { LemonDialog } from '@posthog/lemon-ui'

import type { DataCatalogCertificationApi } from './generated/api.schemas'

export function confirmRevokeCertification(certification: DataCatalogCertificationApi, onRevoke: () => void): void {
    LemonDialog.open({
        title: 'Revoke this certification?',
        content: (
            <div className="text-sm text-secondary">
                Revoking deletes the trust mark on {certification.target_name}. This cannot be undone.
            </div>
        ),
        primaryButton: {
            children: 'Revoke',
            status: 'danger',
            onClick: onRevoke,
        },
        secondaryButton: { children: 'Cancel' },
    })
}
