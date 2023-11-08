import { useValues } from 'kea'
import { sidePanelDocsLogic } from './sidePanelDocsLogic'

export const SidePanelDocs = (): JSX.Element => {
    const { path } = useValues(sidePanelDocsLogic)

    // NOTE: Currently we can't detect url changes from the iframe
    return (
        <div className="w-full h-full overflow-hidden">
            <iframe src={`https://posthog.com${path ?? ''}`} title="Docs" className="w-full h-full" />
        </div>
    )
}
