import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { PathCleaningFilter } from '~/types'

import { PathCleanFilters } from './PathCleanFilters'

interface PathCleaningControlsProps {
    localFilters: PathCleaningFilter[]
    setLocalFilters: (filters: PathCleaningFilter[]) => void
    applyGlobal: boolean
    setApplyGlobal: (apply: boolean) => void
    'data-attr'?: string
}

/** An insight's path cleaning configuration: its local rules plus the switch applying the
 * project-wide rules, shared between the paths and journeys editors. */
export function PathCleaningControls({
    localFilters,
    setLocalFilters,
    applyGlobal,
    setApplyGlobal,
    'data-attr': dataAttr,
}: PathCleaningControlsProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const hasGlobalRules = (currentTeam?.path_cleaning_filters || []).length > 0

    return (
        <>
            <PathCleanFilters filters={localFilters} setFilters={setLocalFilters} />
            <Tooltip
                title={
                    hasGlobalRules
                        ? 'Apply the path cleaning rules from the project settings.'
                        : 'The project has no path cleaning rules. Configure them via the gear icon.'
                }
            >
                {/* This div is necessary for the tooltip to work. */}
                <div className="inline-block mt-4 w-full">
                    <LemonSwitch
                        disabled={!hasGlobalRules}
                        checked={hasGlobalRules && applyGlobal}
                        onChange={setApplyGlobal}
                        label={
                            <div className="flex items-center">
                                <span>Apply global path URL cleaning</span>
                                <LemonButton
                                    icon={<IconGear />}
                                    to={urls.settings('project-product-analytics', 'path-cleaning')}
                                    size="small"
                                    noPadding
                                    className="ml-1"
                                />
                            </div>
                        }
                        fullWidth
                        bordered
                        data-attr={dataAttr}
                    />
                </div>
            </Tooltip>
        </>
    )
}
