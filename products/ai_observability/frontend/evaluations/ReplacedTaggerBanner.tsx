import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { replacedTaggerLogic } from './replacedTaggerLogic'

export interface ReplacedTaggerBannerProps {
    evaluationId: string
}

export function ReplacedTaggerBanner({ evaluationId }: ReplacedTaggerBannerProps): JSX.Element | null {
    const { replacedTagger } = useValues(replacedTaggerLogic({ evaluationId }))

    if (!replacedTagger) {
        return null
    }
    return (
        <LemonBanner
            type="info"
            action={{
                children: 'View past tags',
                to: urls.aiObservabilityTag(replacedTagger.id),
                'data-attr': 'evaluation-replaced-tagger-view-tags',
            }}
        >
            This evaluation replaces the tagger <span className="font-semibold">{replacedTagger.name}</span>. The tags
            it sent before stay on the tagger page.
        </LemonBanner>
    )
}
