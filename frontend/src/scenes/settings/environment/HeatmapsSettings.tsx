import { useActions } from 'kea'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { TeamSettingToggle } from '../components/TeamSettingToggle'

export function HeatmapsSettings(): JSX.Element {
    const { reportHeatmapsToggled } = useActions(eventUsageLogic)

    return (
        <TeamSettingToggle field="heatmaps_opt_in" label="Enable heatmaps for web" onChange={reportHeatmapsToggled} />
    )
}
