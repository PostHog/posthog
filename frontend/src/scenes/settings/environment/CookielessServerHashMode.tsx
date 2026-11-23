import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonSwitch } from '@posthog/lemon-ui'
import { Button, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { teamLogic } from 'scenes/teamLogic'

import { CookielessServerHashMode } from '~/types'

export function CookielessServerHashModeSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const savedEnabled =
        (currentTeam?.cookieless_server_hash_mode ?? CookielessServerHashMode.Disabled) !==
        CookielessServerHashMode.Disabled
    const [enabled, setEnabled] = useState<boolean>(savedEnabled)

    const handleSave = (): void => {
        updateCurrentTeam({
            cookieless_server_hash_mode: enabled
                ? CookielessServerHashMode.Stateful
                : CookielessServerHashMode.Disabled,
        })
    }

    const saveDisabledReason = enabled === savedEnabled ? 'No changes to save' : restrictedReason

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-4">
                <Item tone="info" size="sm" className="self-stretch">
                    <ItemContent>
                        <ItemDescription>
                            When cookieless tracking is enabled, the IP address is hashed into the distinct ID and
                            stripped before transformations run, so IP-based transformations like GeoIP enrichment and
                            bot detection will not enrich those events.
                        </ItemDescription>
                    </ItemContent>
                </Item>
                <QuillSettingSwitch
                    label="Enable cookieless tracking"
                    checked={enabled}
                    onCheckedChange={setEnabled}
                    disabledReason={restrictedReason}
                    dataAttr="cookieless-tracking-toggle"
                />
                <Button variant="primary" onClick={handleSave} disabledReason={saveDisabledReason}>
                    Save
                </Button>
            </div>
        )
    }

    return (
        <>
            <LemonBanner type="info" className="mb-4">
                When cookieless tracking is enabled, the IP address is hashed into the distinct ID and stripped before
                transformations run, so IP-based transformations like GeoIP enrichment and bot detection will not enrich
                those events.
            </LemonBanner>
            <LemonSwitch
                label="Enable cookieless tracking"
                checked={enabled}
                onChange={setEnabled}
                disabledReason={restrictedReason}
                data-attr="cookieless-tracking-toggle"
            />
            <div className="mt-4">
                <LemonButton type="primary" onClick={handleSave} disabledReason={saveDisabledReason}>
                    Save
                </LemonButton>
            </div>
        </>
    )
}
