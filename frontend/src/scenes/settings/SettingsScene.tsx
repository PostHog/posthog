import { SceneExport } from 'scenes/sceneTypes'
import { capitalizeFirstLetter } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { settingsSceneLogic } from './settingsSceneLogic'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { teamLogic } from 'scenes/teamLogic'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { SettingLevelIds } from './types'
import { SettingsRenderer } from './SettingsRenderer'

export const scene: SceneExport = {
    component: SettingsScene,
    logic: settingsSceneLogic,
}

/**
 *
 * Settings can be accessed in multiple ways:
 * 1. Via the main settings page - each section is a separate page
 * 2. Via small popups for individual settings
 * 3. Via the sidepanel (3000) for any section
 */

export function SettingsScene(): JSX.Element {
    const { selectedSectionId, selectedLevel, sections } = useValues(settingsSceneLogic)
    const { selectSection, selectLevel } = useActions(settingsSceneLogic)
    const { currentTeam } = useValues(teamLogic)

    const { location } = useValues(router)

    useAnchor(location.hash)

    return (
        <>
            <div className="flex items-start gap-8">
                <div className="shrink-0 w-60 sticky top-16">
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

                <div className="flex-1 overflow-hidden space-y-2">
                    {selectedLevel === 'project' && (
                        <LemonBanner type="info">
                            These settings only apply to {currentTeam?.name ?? 'the current project'}.
                        </LemonBanner>
                    )}
                    <SettingsRenderer />
                </div>
            </div>
        </>
    )
}
