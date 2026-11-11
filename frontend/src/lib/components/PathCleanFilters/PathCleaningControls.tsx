import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { PathCleaningFilter } from '~/types'

import { PathCleanFilters } from './PathCleanFilters'
import { QuillPathCleaningGlobalSwitch } from './QuillPathCleaningGlobalSwitch'

interface PathCleaningControlsProps {
    localFilters: PathCleaningFilter[]
    setLocalFilters: (filters: PathCleaningFilter[]) => void
    applyGlobal: boolean
    setApplyGlobal: (apply: boolean) => void
    'data-attr'?: string
}

const APPLY_GLOBAL_INFO = 'Apply the path cleaning rules from the project settings.'
const NO_GLOBAL_RULES_REASON = 'The project has no path cleaning rules. Configure them via the gear icon.'

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
    const quillSurface = useQuillSurface()
    const hasGlobalRules = (currentTeam?.path_cleaning_filters || []).length > 0
    const settingsUrl = urls.settings('project-product-analytics', 'path-cleaning')

    if (quillSurface) {
        return (
            <div className="flex flex-col gap-4">
                <PathCleanFilters filters={localFilters} setFilters={setLocalFilters} />
                <QuillPathCleaningGlobalSwitch
                    checked={hasGlobalRules && applyGlobal}
                    onChange={setApplyGlobal}
                    info={APPLY_GLOBAL_INFO}
                    disabledReason={hasGlobalRules ? undefined : NO_GLOBAL_RULES_REASON}
                    settingsUrl={settingsUrl}
                    data-attr={dataAttr}
                />
            </div>
        )
    }

    return (
        <>
            <PathCleanFilters filters={localFilters} setFilters={setLocalFilters} />
            <Tooltip title={hasGlobalRules ? APPLY_GLOBAL_INFO : NO_GLOBAL_RULES_REASON}>
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
                                    to={settingsUrl}
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
