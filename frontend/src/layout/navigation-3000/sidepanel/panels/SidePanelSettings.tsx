import { useValues } from 'kea'
import { sidePanelSettingsLogic } from './sidePanelSettingsLogic'
import { SettingsRenderer } from 'scenes/settings/SettingsRenderer'

export const SidePanelSettings = (): JSX.Element => {
    const { settings } = useValues(sidePanelSettingsLogic)

    // NOTE: Currently we can't detect url changes from the iframe
    return (
        <div className="p-4">
            <SettingsRenderer {...settings} />
        </div>
    )
}
