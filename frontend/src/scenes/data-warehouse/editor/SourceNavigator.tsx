import clsx from 'clsx'
import { useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'

import { editorSizingLogic } from './editorSizingLogic'

export function SourceNavigator(): JSX.Element {
    const { sourceNavigatorWidth, sourceNavigatorResizerProps } = useValues(editorSizingLogic)

    return (
        <div
            ref={sourceNavigatorResizerProps.containerRef}
            className={clsx('relative flex', 'bg-white', 'h-full')}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: `${sourceNavigatorWidth}px`,
            }}
        >
            <Resizer {...sourceNavigatorResizerProps} />
        </div>
    )
}
