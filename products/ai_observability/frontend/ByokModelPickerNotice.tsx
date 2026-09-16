import { LemonBanner, Link } from '@posthog/lemon-ui'

import { getModelPickerFooterLink } from './ModelPicker'

export interface ByokModelPickerNoticeProps {
    hasGroups: boolean
    loading: boolean
    loadFailed: boolean
    onRetry: () => void
}

/** Explains an empty or short model picker on the surfaces that only run on the team's own provider keys. */
export function ByokModelPickerNotice({
    hasGroups,
    loading,
    loadFailed,
    onRetry,
}: ByokModelPickerNoticeProps): JSX.Element | null {
    if (loading) {
        return null
    }

    if (loadFailed) {
        return (
            <LemonBanner
                type="error"
                className="mt-1 text-xs"
                action={{ onClick: onRetry, children: 'Try again', 'data-attr': 'byok-models-retry' }}
            >
                Couldn't load models for one of your provider keys.
            </LemonBanner>
        )
    }

    if (!hasGroups) {
        const settingsLink = getModelPickerFooterLink(false)
        return (
            <p className="text-xs text-secondary mt-1">
                No models available. <Link to={settingsLink.to}>{settingsLink.label}</Link> to choose one.
            </p>
        )
    }

    return null
}
