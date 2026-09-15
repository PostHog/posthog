import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { FeatureRequestCreateModal } from './FeatureRequestCreateModal'
import { type FeatureRequestCreatePrefill, featureRequestsLogic } from './featureRequestsLogic'

export interface FileFeatureRequestButtonProps {
    prefill: FeatureRequestCreatePrefill
}

/** Files a Customer analytics feature request from another product's surface, such as a support ticket. */
export function FileFeatureRequestButton({ prefill }: FileFeatureRequestButtonProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const [filing, setFiling] = useState(false)

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS]) {
        return null
    }

    const disabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )

    // featureRequestsLogic loads the request list, the product areas and the accounts when it
    // mounts, so keep it out of the host scene until someone files a request.
    return filing ? (
        <FeatureRequestFiler prefill={prefill} disabledReason={disabledReason} />
    ) : (
        <FileFeatureRequestTrigger onClick={() => setFiling(true)} disabledReason={disabledReason} />
    )
}

function FeatureRequestFiler({
    prefill,
    disabledReason,
}: FileFeatureRequestButtonProps & { disabledReason: string | null }): JSX.Element {
    const { openCreateRequest } = useActions(featureRequestsLogic)

    useOnMountEffect(() => {
        openCreateRequest(prefill)
    })

    return (
        <>
            <FileFeatureRequestTrigger onClick={() => openCreateRequest(prefill)} disabledReason={disabledReason} />
            <FeatureRequestCreateModal />
        </>
    )
}

function FileFeatureRequestTrigger({
    onClick,
    disabledReason,
}: {
    onClick: () => void
    disabledReason: string | null
}): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconPlus />}
            onClick={onClick}
            disabledReason={disabledReason ?? undefined}
            data-attr="file-feature-request"
        >
            File feature request
        </LemonButton>
    )
}
