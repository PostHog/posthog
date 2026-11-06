import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { PRODUCT_ACTIVITY_SETUP } from '../../components/Accounts/accountProductActivityUrl'
import { accountViewsLogic } from './accountViewsLogic'

export function AccountProductActivitySetup({ projectId }: { projectId: number }): JSX.Element | null {
    const { currentLocation } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openCreateEditor, setEditorName, addEditorComponent } = useActions(accountViewsLogic({ projectId }))
    if (
        currentLocation.searchParams.setup !== PRODUCT_ACTIVITY_SETUP ||
        !featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS] ||
        !featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_DOT_MATRIX]
    ) {
        return null
    }
    return (
        <LemonBanner
            type="info"
            action={{
                children: 'Add view',
                'data-attr': 'account-product-activity-setup',
                onClick: () => {
                    openCreateEditor()
                    setEditorName('Product activity')
                    addEditorComponent('dot_matrix')
                    const { setup: _, ...searchParams } = currentLocation.searchParams
                    router.actions.replace(currentLocation.pathname, searchParams, currentLocation.hashParams)
                },
            }}
        >
            Set up a product activity view for this account. Add a Dot matrix tile, then choose its data source.
        </LemonBanner>
    )
}
