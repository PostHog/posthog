import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

type BounceRatePageViewMode = NonNullable<HogQLQueryModifiers['bounceRatePageViewMode']>

const bounceRatePageViewModeOptions: LemonRadioOption<BounceRatePageViewMode>[] = [
    {
        value: 'count_pageviews',
        label: (
            <>
                <div>Counts pageviews</div>
                <div className="text-secondary">
                    This is the default. Counts <code>$pageview</code> events in a session as part of the bounce rate
                    calculation.
                </div>
            </>
        ),
    },
    {
        value: 'uniq_urls',
        label: (
            <>
                <div>Counts unique urls visited</div>
                <div className="text-secondary">
                    Counts the number of unique url visited as part of the bounce rate calculation
                </div>
            </>
        ),
    },
    {
        value: 'uniq_page_screen_autocaptures',
        label: (
            <>
                <div>Use uniqUpTo</div>
                <div className="text-secondary">
                    Uses the <code>uniqUpTo</code> function to count if the total unique pageviews + screen events +
                    autocaptures is &gte; 2
                </div>
            </>
        ),
    },
]

export function BounceRatePageViewModeSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { reportBounceRatePageViewModeUpdated } = useActions(eventUsageLogic)

    const savedBounceRatePageViewMode =
        currentTeam?.modifiers?.bounceRatePageViewMode ??
        currentTeam?.default_modifiers?.bounceRatePageViewMode ??
        'count_pageviews'
    const [bounceRatePageViewMode, setBounceRatePageViewMode] =
        useState<BounceRatePageViewMode>(savedBounceRatePageViewMode)

    const handleChange = (mode: BounceRatePageViewMode): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, bounceRatePageViewMode: mode } })
        reportBounceRatePageViewModeUpdated(mode)
    }

    return (
        <>
            <p>
                Choose how pageviews are counted, as part of the bounce rate calculation. Note that other factors are
                taken into account, e.g. the number of autocaptures, and the session duration.
            </p>
            <LemonRadio
                value={bounceRatePageViewMode}
                onChange={setBounceRatePageViewMode}
                options={bounceRatePageViewModeOptions}
            />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(bounceRatePageViewMode)}
                    disabledReason={
                        bounceRatePageViewMode === savedBounceRatePageViewMode ? 'No changes to save' : undefined
                    }
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
