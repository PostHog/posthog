import { SceneExport } from 'scenes/sceneTypes'
import { SettingLevels, SettingsSections } from './SettingsMap'
import { capitalizeFirstLetter } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { settingsLogic } from './settingsLogic'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'

export const scene: SceneExport = {
    component: SettingsScene,
}

/**
 *
 * Settings can be accessed in multiple ways:
 * 1. Via the main settings page - each section is a separate page
 * 2. Via small popups for individual settings
 * 3. Via the sidepanel (3000) for any section
 */

export function SettingsScene(): JSX.Element {
    const { selectedSectionId, selectedLevel, settings, sections } = useValues(settingsLogic)
    const { selectSection, selectLevel } = useActions(settingsLogic)

    // const { location } = useValues(router)

    // useAnchor(location.hash)

    return (
        <>
            <div className="flex items-start sticky top-0 gap-8">
                <div className="flex-0 w-60">
                    <ul className="space-y-px">
                        {SettingLevels.map((level) => (
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

                <div className="flex-1 space-y-8">
                    {settings.map((x) => (
                        <div key={x.id} id={x.id}>
                            <h2 className="">{x.title}</h2>
                            {x.description && <p>{x.description}</p>}

                            {x.component}
                        </div>
                    ))}
                </div>
            </div>
        </>
    )
}
