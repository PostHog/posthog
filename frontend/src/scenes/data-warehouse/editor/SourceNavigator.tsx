import { useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'

import { DatabaseTableTreeWithItems } from '../external/DataWarehouseTables'
import { editorSizingLogic } from './editorSizingLogic'
import { SchemaSearch } from './SchemaSearch'

export function SourceNavigator(): JSX.Element {
    const { sourceNavigatorWidth, sourceNavigatorResizerProps } = useValues(editorSizingLogic)

    return (
        <div
            ref={sourceNavigatorResizerProps.containerRef}
            className="relative flex flex-col bg-bg-3000 h-full overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: `${sourceNavigatorWidth}px`,
            }}
        >
            <SchemaSearch />
            <DatabaseTableTreeWithItems inline collapsible={false} />
            <Resizer {...sourceNavigatorResizerProps} />
        </div>
    )
}
