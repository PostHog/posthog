import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

export interface DowngradeFeature {
    title: string
    warning?: boolean
}

interface FeatureDowngradeModalProps {
    isOpen: boolean
    onClose: () => void
    onDowngrade: () => void
    title: string
    subtitle?: string
    features: DowngradeFeature[]
}

export function FeatureDowngradeModal({
    isOpen,
    onClose,
    onDowngrade,
    title,
    subtitle = 'You are about to lose access to the following features:',
    features,
}: FeatureDowngradeModalProps): JSX.Element {
    return (
        <LemonModal
            title={title}
            description={subtitle}
            isOpen={isOpen}
            onClose={onClose}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" status="danger" onClick={onDowngrade}>
                        Continue Unsubscribing
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                {features.map((feature, index) => (
                    <div key={index} className="flex items-center gap-2">
                        <IconWarning className="text-warning" />
                        <div>{feature.title}</div>
                    </div>
                ))}
            </div>
        </LemonModal>
    )
}
