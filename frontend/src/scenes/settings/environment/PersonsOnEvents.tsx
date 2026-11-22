import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonTag } from '@posthog/lemon-ui'
import { Badge } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

import { QuillTeamSettingRadio } from '../components/QuillTeamSettingRadio'

type PoEMode = NonNullable<HogQLQueryModifiers['personsOnEventsMode']>

const RECOMMENDED_POE_MODE: PoEMode = 'person_id_override_properties_on_events'
const RECOMMENDED_POE_LABEL = 'Use person properties from the time of the event'

const POE_OPTIONS: LemonRadioOption<PoEMode>[] = [
    {
        value: RECOMMENDED_POE_MODE,
        label: (
            <span className="inline-flex items-center gap-1.5">
                {RECOMMENDED_POE_LABEL}
                <LemonTag>RECOMMENDED</LemonTag>
            </span>
        ),
        description: (
            <>
                Fast queries. If the person property is updated, query results on past data <em>won't</em> change.
            </>
        ),
    },
    {
        value: 'person_id_override_properties_joined',
        label: 'Use person properties as of running the query',
        description: (
            <>
                Slower queries. If the person property is updated, query results on past data <em>will</em> change
                accordingly.
            </>
        ),
    },
    {
        value: 'person_id_no_override_properties_on_events',
        label: 'Use person IDs and person properties from the time of the event',
        description: (
            <>
                Fastest queries,{' '}
                <span className="underline">but funnels and unique user counts will be inaccurate</span>. If the person
                property is updated, query results on past data <em>won't</em> change.
            </>
        ),
    },
]

export function PersonsOnEvents(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportPoEModeUpdated } = useActions(eventUsageLogic)
    const { currentTeam } = useValues(teamLogic)
    const savedPoEMode: PoEMode =
        currentTeam?.modifiers?.personsOnEventsMode ?? currentTeam?.default_modifiers?.personsOnEventsMode ?? 'disabled'
    const [poeMode, setPoeMode] = useState<PoEMode>(savedPoEMode)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const poeOptions = POE_OPTIONS.map((o) => ({ ...o, disabledReason: restrictedReason ?? undefined }))

    const handleChange = (mode: PoEMode): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, personsOnEventsMode: mode } })
        posthog.capture('user changed personsOnEventsMode setting', { personsOnEventsMode: mode })
        reportPoEModeUpdated(mode)
    }

    const saveDisabledReason = poeMode === savedPoEMode ? 'No changes to save' : restrictedReason

    if (todayRailNav) {
        const quillPoeOptions = poeOptions.map((option) =>
            option.value === RECOMMENDED_POE_MODE
                ? {
                      ...option,
                      label: (
                          <span className="inline-flex flex-wrap items-center gap-1.5">
                              {RECOMMENDED_POE_LABEL}
                              <Badge>RECOMMENDED</Badge>
                          </span>
                      ),
                  }
                : option
        )

        return (
            <QuillTeamSettingRadio
                options={quillPoeOptions}
                value={poeMode}
                onValueChange={setPoeMode}
                onSave={() => handleChange(poeMode)}
                saveDisabledReason={saveDisabledReason}
            />
        )
    }

    return (
        <>
            <LemonRadio value={poeMode} onChange={setPoeMode} options={poeOptions} />
            <div className="mt-4">
                <LemonButton type="primary" onClick={() => handleChange(poeMode)} disabledReason={saveDisabledReason}>
                    Save
                </LemonButton>
            </div>
        </>
    )
}
