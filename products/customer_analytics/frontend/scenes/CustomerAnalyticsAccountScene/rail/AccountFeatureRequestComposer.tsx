import { useActions } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { FeatureRequestCreateModal } from 'products/customer_analytics/frontend/components/FeatureRequests/FeatureRequestCreateModal'
import { featureRequestsLogic } from 'products/customer_analytics/frontend/components/FeatureRequests/featureRequestsLogic'

interface AccountFeatureRequestComposerProps {
    accountId: string
}

// The feature requests logic loads the whole request list when it mounts, so it only
// mounts once a person asks for the composer.
export function AccountFeatureRequestComposer({ accountId }: AccountFeatureRequestComposerProps): JSX.Element {
    const { openCreateRequest, setAccountId } = useActions(featureRequestsLogic)

    useOnMountEffect(() => {
        openCreateRequest()
        setAccountId(accountId)
    })

    return <FeatureRequestCreateModal />
}
