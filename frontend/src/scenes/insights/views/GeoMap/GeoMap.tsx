import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

export function GeoMap(): JSX.Element {
    const { insight } = useValues(insightLogic)
    console.log(insight)

    return <div>map comes here {insight.result?.length ?? 'none'}</div>
}
