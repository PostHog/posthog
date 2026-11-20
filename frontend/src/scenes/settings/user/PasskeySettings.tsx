import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'
import { Item, ItemContent, ItemDescription, Skeleton } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { userLogic } from 'scenes/userLogic'

import { PasskeyAddForm, PasskeyAddFormEmpty } from './PasskeyAddForm'
import { PasskeyList } from './PasskeyList'
import { PasskeyModals } from './PasskeyModals'
import { passkeySettingsLogic } from './passkeySettingsLogic'

export function PasskeySettings(): JSX.Element {
    const { passkeys, passkeysLoading } = useValues(passkeySettingsLogic)
    const { user } = useValues(userLogic)
    const { loadPasskeys } = useActions(passkeySettingsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(() => {
        loadPasskeys()
    }, [loadPasskeys])

    if (passkeysLoading) {
        return todayRailNav ? (
            <div className="flex flex-col gap-4">
                <Skeleton className="h-32" />
                <Skeleton className="h-24" />
            </div>
        ) : (
            <div className="space-y-4">
                <LemonSkeleton className="h-32" />
                <LemonSkeleton className="h-24" />
            </div>
        )
    }

    const hasExistingPasskeys = passkeys.length > 0
    const hasSSOEnforcement = !!user?.has_sso_enforcement

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                {hasSSOEnforcement && (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                Passkeys can't be added because your organization requires SSO.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}
                {!hasSSOEnforcement && (hasExistingPasskeys ? <PasskeyAddForm /> : <PasskeyAddFormEmpty />)}
                {hasExistingPasskeys && <PasskeyList />}
                <PasskeyModals />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            {hasSSOEnforcement && (
                <LemonBanner type="warning">
                    Passkeys can't be added because your organization requires SSO.
                </LemonBanner>
            )}
            {!hasSSOEnforcement && (hasExistingPasskeys ? <PasskeyAddForm /> : <PasskeyAddFormEmpty />)}
            {hasExistingPasskeys && <PasskeyList />}
            <PasskeyModals />
        </div>
    )
}
