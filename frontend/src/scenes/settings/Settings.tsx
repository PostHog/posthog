import { LemonBanner, LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { IconChevronRight, IconLink } from 'lib/lemon-ui/icons'
import { SettingsLogicProps, settingsLogic } from './settingsLogic'
import { useActions, useValues } from 'kea'
import { SettingLevelIds } from './types'
import clsx from 'clsx'
import { capitalizeFirstLetter } from 'lib/utils'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { teamLogic } from 'scenes/teamLogic'
import { useEffect } from 'react'
import { useState } from 'react'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function Settings({
    hideSections = false,
    ...props
}: SettingsLogicProps & { hideSections?: boolean }): JSX.Element {
    const { selectedSectionId, selectedSection, selectedLevel, sections } = useValues(settingsLogic(props))
    const { selectSection, selectLevel } = useActions(settingsLogic(props))
    const { currentTeam } = useValues(teamLogic)
    const is3000 = useFeatureFlag('POSTHOG_3000')

    const [navExpanded, setNavExpanded] = useState(false)

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        700: 'medium',
    })

    const isCompact = size === 'small'

    useEffect(() => {
        setNavExpanded(false)
    }, [selectedSectionId, selectedLevel])

    const showSections = !hideSections && !(isCompact && !navExpanded)

    return (
        <div className={clsx('flex', isCompact ? 'flex-col' : 'gap-8 items-start', !is3000 && 'mt-4')} ref={ref}>
            {showSections ? (
                <div
                    className={clsx('shrink-0', {
                        'sticky w-60': !isCompact,
                        'top-16': !isCompact && is3000,
                        'top-2': !isCompact && !is3000,
                    })}
                >
                    <ul className="space-y-px">
                        {SettingLevelIds.map((level) => (
                            <li key={level} className="space-y-px">
                                <LemonButton
                                    onClick={() => selectLevel(level)}
                                    size="small"
                                    fullWidth
                                    active={selectedLevel === level && !selectedSectionId}
                                >
                                    <span className={clsx('text-muted-alt', level === selectedLevel && 'font-bold')}>
                                        {capitalizeFirstLetter(level)}
                                    </span>
                                </LemonButton>

                                <ul className="space-y-px">
                                    {sections
                                        .filter((x) => x.level === level)
                                        .map((section) => (
                                            <li key={section.id} className="pl-4">
                                                <LemonButton
                                                    onClick={() => selectSection(section.id)}
                                                    size="small"
                                                    fullWidth
                                                    active={selectedSectionId === section.id}
                                                >
                                                    {section.title}
                                                </LemonButton>
                                            </li>
                                        ))}
                                </ul>
                            </li>
                        ))}
                    </ul>
                </div>
            ) : isCompact ? (
                <LemonButton fullWidth sideIcon={<IconChevronRight />} onClick={() => setNavExpanded(true)}>
                    {capitalizeFirstLetter(selectedLevel)}
                    {selectedSection ? ` / ${selectedSection.title}` : null}
                </LemonButton>
            ) : null}

            {isCompact ? <LemonDivider /> : null}

            <div className="flex-1 w-full space-y-2 overflow-hidden">
                {selectedLevel === 'project' && (
                    <LemonBanner type="info">
                        These settings only apply to {currentTeam?.name ?? 'the current project'}.
                    </LemonBanner>
                )}

                <SettingsRenderer {...props} />
            </div>
        </div>
    )
}

function SettingsRenderer(props: SettingsLogicProps): JSX.Element {
    const { settings } = useValues(settingsLogic(props))
    const { selectSetting } = useActions(settingsLogic(props))

    return (
        <div className="space-y-8">
            {settings.map((x) => (
                <div key={x.id} className="relative">
                    <div
                        id={x.id}
                        className="absolute" // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            marginTop: '-3.5rem', // Account for top bar when scrolling to anchor
                        }}
                    />
                    <h2 className="flex gap-2 items-center">
                        {x.title} <LemonButton icon={<IconLink />} size="small" onClick={() => selectSetting?.(x.id)} />
                    </h2>
                    {x.description && <p>{x.description}</p>}

                    {x.component}
                </div>
            ))}
        </div>
    )
}
