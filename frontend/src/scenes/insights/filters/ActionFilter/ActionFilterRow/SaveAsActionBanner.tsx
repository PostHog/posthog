import { useActions, useMountedLogic } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

import { saveAsActionLogic } from 'products/actions/frontend/logics/saveAsActionLogic'

import { LocalFilter } from '../entityFilterLogic'
import { isAutocaptureFilterWithElements } from './saveAsActionUtils'

interface SaveAsActionBannerProps {
    filter: LocalFilter
}

export function SaveAsActionBanner({ filter }: SaveAsActionBannerProps): JSX.Element | null {
    useMountedLogic(saveAsActionLogic)
    const { saveFromFilter } = useActions(saveAsActionLogic)

    if (!isAutocaptureFilterWithElements(filter)) {
        return null
    }

    return (
        <FlaggedFeature flag={FEATURE_FLAGS.AUTOCAPTURE_SAVE_AS_ACTION}>
            <PostHogCaptureOnViewed name="autocapture-series-save-as-action-banner-shown">
                <LemonBanner
                    type="info"
                    className="mt-2"
                    dismissKey="autocapture-save-as-action-nudge"
                    action={{
                        children: 'Save as action',
                        onClick: () => saveFromFilter(filter),
                        'data-attr': 'autocapture-save-as-action',
                    }}
                >
                    Save this autocapture filter as a reusable action.
                </LemonBanner>
            </PostHogCaptureOnViewed>
        </FlaggedFeature>
    )
}
