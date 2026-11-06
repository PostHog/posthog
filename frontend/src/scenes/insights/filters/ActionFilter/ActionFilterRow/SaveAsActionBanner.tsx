import { LemonBanner } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { saveActionFromSeriesNode } from '~/models/saveAsActionDialog'

import { SeriesNode } from '../seriesNode'
import { isAutocaptureSeriesWithElements } from './saveAsActionUtils'

interface SaveAsActionBannerProps {
    node: SeriesNode
}

export function SaveAsActionBanner({ node }: SaveAsActionBannerProps): JSX.Element | null {
    if (!isAutocaptureSeriesWithElements(node)) {
        return null
    }

    return (
        <PostHogCaptureOnViewed name="autocapture-series-save-as-action-banner-shown">
            <LemonBanner
                type="info"
                className="mt-2"
                dismissKey="autocapture-save-as-action-nudge"
                action={{
                    children: 'Save as action',
                    onClick: () => saveActionFromSeriesNode(node),
                    'data-attr': 'autocapture-save-as-action',
                }}
            >
                Save this autocapture filter as a reusable action.
            </LemonBanner>
        </PostHogCaptureOnViewed>
    )
}
