import { LemonBanner } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { saveActionFromFilter } from '~/models/saveAsActionDialog'

import { LocalFilter } from '../entityFilterLogic'
import { isAutocaptureFilterWithElements } from './saveAsActionUtils'

interface SaveAsActionBannerProps {
    filter: LocalFilter
}

export function SaveAsActionBanner({ filter }: SaveAsActionBannerProps): JSX.Element | null {
    if (!isAutocaptureFilterWithElements(filter)) {
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
                    onClick: () => saveActionFromFilter(filter),
                    'data-attr': 'autocapture-save-as-action',
                }}
            >
                Save this autocapture filter as a reusable action.
            </LemonBanner>
        </PostHogCaptureOnViewed>
    )
}
