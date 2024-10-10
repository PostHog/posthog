import { useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'

import { editorSizingLogic } from './editorSizingLogic'

export function QueryPane(): JSX.Element {
    const { queryPaneHeight, queryPaneResizerProps } = useValues(editorSizingLogic)
    return (
        <div
            className="relative flex w-full bg-bg-3000-light"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                height: `${queryPaneHeight}px`,
            }}
            ref={queryPaneResizerProps.containerRef}
        >
            <Resizer {...queryPaneResizerProps} />
        </div>
    )
}
