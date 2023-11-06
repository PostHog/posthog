import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { AllSettings } from './SettingsMap'

export const SettingsSections = {}

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
    // const { location } = useValues(router)

    // useAnchor(location.hash)

    return (
        <>
            <div className="flex items-start sticky top-0 gap-8">
                <div className="flex-0">
                    <ul>
                        {AllSettings.map((section) => (
                            <li key={section.id}>
                                <span className="text-muted-alt">{section.title}</span>
                                <ul>
                                    {section.settings.map((setting) => (
                                        <li key={setting.id} className="pl-4">
                                            {setting.title}
                                        </li>
                                    ))}
                                </ul>
                            </li>
                        ))}
                    </ul>
                </div>

                <div className="flex-1 space-y-4">
                    {AllSettings.map((x) => (
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
