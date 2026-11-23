import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { Button, Heading, Item, ItemActions, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import {
    AccountPropertyConfigurator,
    type AccountPropertyConfiguratorProps,
} from 'products/customer_analytics/frontend/scenes/CustomerAnalyticsAccountScene/components/AccountPropertyConfigurator'
import { QuillAccountPropertyConfigurator } from 'products/customer_analytics/frontend/scenes/CustomerAnalyticsAccountScene/components/QuillAccountPropertyConfigurator'

import { defaultPinnedAccountPropertiesLogic } from './defaultPinnedAccountPropertiesLogic'

export function DefaultPinnedAccountProperties(): JSX.Element {
    const {
        canSave,
        defaultPinnedProperties,
        definitionsLoadFailed,
        definitionsLoading,
        draftPinnedPropertyKeys,
        isOpen,
        propertyOptions,
        saveFailed,
        saving,
        stalePinnedProperties,
    } = useValues(defaultPinnedAccountPropertiesLogic)
    const {
        closeConfigurator,
        openConfigurator,
        retryDefinitions,
        saveDefaultPinnedProperties,
        setDraftPinnedPropertyKeys,
    } = useActions(defaultPinnedAccountPropertiesLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const configureDisabledReason =
        restrictedReason ??
        (definitionsLoading ? 'Loading properties' : definitionsLoadFailed ? 'Could not load properties' : undefined)

    const selectedSummary =
        defaultPinnedProperties.length === 0
            ? 'No default properties selected.'
            : `${defaultPinnedProperties.length} default ${
                  defaultPinnedProperties.length === 1 ? 'property' : 'properties'
              } selected.`

    const configuratorProps: AccountPropertyConfiguratorProps = {
        isOpen,
        title: 'Default pinned properties',
        options: propertyOptions,
        pinnedPropertyKeys: draftPinnedPropertyKeys,
        saving,
        onChange: setDraftPinnedPropertyKeys,
        onSave: saveDefaultPinnedProperties,
        onCancel: closeConfigurator,
        saveDisabledReason: restrictedReason ?? (!saving && !canSave ? 'No changes to save' : undefined),
    }

    const configurator = <AccountPropertyConfigurator {...configuratorProps} />

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-col gap-1">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Default pinned properties
                        </Heading>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Choose the account properties people see until they save their own selection.
                        </Text>
                    </div>
                    <Button
                        variant="outline"
                        onClick={openConfigurator}
                        disabledReason={configureDisabledReason}
                        data-attr="configure-default-pinned-account-properties"
                    >
                        Configure defaults
                    </Button>
                </div>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {selectedSummary}
                </Text>
                {definitionsLoadFailed ? (
                    <Item tone="destructive" size="sm" className="flex-wrap">
                        <ItemContent>
                            <ItemDescription>
                                Could not load the properties available for project defaults.
                            </ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button variant="outline" onClick={retryDefinitions} loading={definitionsLoading}>
                                Try again
                            </Button>
                        </ItemActions>
                    </Item>
                ) : null}
                {!definitionsLoading && !definitionsLoadFailed && stalePinnedProperties.length > 0 ? (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                Some default properties are no longer available. Open the configurator and save to
                                remove them.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                ) : null}
                {saveFailed ? (
                    <Item tone="destructive" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                Could not save the default pinned properties. Review them and try again.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                ) : null}
                <QuillAccountPropertyConfigurator {...configuratorProps} />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                    <h3 className="mb-0">Default pinned properties</h3>
                    <p className="text-secondary mb-0">
                        Choose the account properties people see until they save their own selection.
                    </p>
                </div>
                <LemonButton
                    type="secondary"
                    onClick={openConfigurator}
                    disabledReason={configureDisabledReason}
                    data-attr="configure-default-pinned-account-properties"
                >
                    Configure defaults
                </LemonButton>
            </div>
            <p className="mb-0 text-sm text-secondary">{selectedSummary}</p>
            {definitionsLoadFailed ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: retryDefinitions, loading: definitionsLoading }}
                >
                    Could not load the properties available for project defaults.
                </LemonBanner>
            ) : null}
            {!definitionsLoading && !definitionsLoadFailed && stalePinnedProperties.length > 0 ? (
                <LemonBanner type="warning">
                    Some default properties are no longer available. Open the configurator and save to remove them.
                </LemonBanner>
            ) : null}
            {saveFailed ? (
                <LemonBanner type="error">
                    Could not save the default pinned properties. Review them and try again.
                </LemonBanner>
            ) : null}
            {configurator}
        </div>
    )
}
