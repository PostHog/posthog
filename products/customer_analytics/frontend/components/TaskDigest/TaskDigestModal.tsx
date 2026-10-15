import { LemonModal } from '@posthog/lemon-ui'

import { CustomerAnalyticsTaskDigest } from './CustomerAnalyticsTaskDigest'

export function TaskDigestModal({ onClose }: { onClose: () => void }): JSX.Element {
    return (
        <LemonModal isOpen onClose={onClose} title="Task digest emails" width={600}>
            <CustomerAnalyticsTaskDigest source="tasks" />
        </LemonModal>
    )
}
