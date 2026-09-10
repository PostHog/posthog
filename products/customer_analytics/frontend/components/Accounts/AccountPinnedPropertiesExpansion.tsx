import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { accountSidebarConfigLogic } from '../../scenes/CustomerAnalyticsAccountScene/accountSidebarConfigLogic'
import { accountSidebarPropertiesLogic } from '../../scenes/CustomerAnalyticsAccountScene/accountSidebarPropertiesLogic'
import { AccountPropertyValue } from '../../scenes/CustomerAnalyticsAccountScene/components/AccountPropertyValue'

export function AccountPinnedPropertiesExpansion({ accountId }: { accountId: string }): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const projectId = currentProjectId ?? 0
    const configLogic = accountSidebarConfigLogic({ projectId })
    const { stalePinnedProperties, configLoading, availableDefinitionsLoading } = useValues(configLogic)
    const { loadConfig, loadAvailableDefinitions } = useActions(configLogic)
    const propertyLogic = accountSidebarPropertiesLogic({ projectId, accountId })
    const { sidebarProperties, propertiesPanelState, propertiesRefreshFailed, propertyDataLoading } =
        useValues(propertyLogic)
    const { loadPropertyData } = useActions(propertyLogic)
    const retryLoading = configLoading || availableDefinitionsLoading || propertyDataLoading
    const retryLoad = (): void => {
        if (!retryLoading) {
            loadConfig()
            loadAvailableDefinitions()
            loadPropertyData()
        }
    }

    return (
        <div
            className="sticky left-0 w-[100cqw] max-w-full p-4 bg-bg-light flex flex-col gap-4"
            data-attr="account-pinned-properties-expansion"
        >
            {propertiesPanelState === 'loading' ? (
                <div className="flex flex-wrap gap-4" data-attr="account-pinned-properties-loading">
                    <LemonSkeleton className="h-10 w-48 max-w-full" />
                    <LemonSkeleton className="h-10 w-48 max-w-full" />
                </div>
            ) : propertiesPanelState === 'failed' ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: retryLoad, loading: retryLoading }}>
                    Could not load pinned properties.
                </LemonBanner>
            ) : (
                <>
                    {propertiesRefreshFailed ? (
                        <LemonBanner
                            type="warning"
                            action={{ children: 'Try again', onClick: retryLoad, loading: retryLoading }}
                        >
                            Could not refresh pinned properties. These values may be out of date.
                        </LemonBanner>
                    ) : null}
                    {stalePinnedProperties.length > 0 ? (
                        <LemonBanner type="warning">
                            <span>Some pinned properties are no longer available. </span>
                            <Link to={urls.customerAnalyticsAccount(accountId)}>
                                Open account details to update your pins.
                            </Link>
                        </LemonBanner>
                    ) : null}
                    {sidebarProperties.length > 0 ? (
                        <dl className="flex flex-wrap gap-4 m-0">
                            {sidebarProperties.map((property) => (
                                <div key={property.key} className="flex flex-col gap-1 max-w-64 min-w-0">
                                    <dt className="text-xs text-secondary truncate" title={property.definition.name}>
                                        {property.definition.name}
                                    </dt>
                                    <dd className="flex flex-col min-w-0 m-0">
                                        <AccountPropertyValue property={property} />
                                    </dd>
                                </div>
                            ))}
                        </dl>
                    ) : stalePinnedProperties.length === 0 ? (
                        <div className="text-sm text-secondary">
                            <span>No pinned properties. </span>
                            <Link to={urls.customerAnalyticsAccount(accountId)}>
                                Open account details to pin properties.
                            </Link>
                        </div>
                    ) : null}
                </>
            )}
        </div>
    )
}
