import { BindLogic } from 'kea'
import { useRef } from 'react'

import { editorSizingLogic } from './editorSizingLogic'
import { QueryTabs } from './QueryTabs'
import { SourceNavigator } from './SourceNavigator'

export function EditorScene(): JSX.Element {
    const ref = useRef(null)
    const navigatorRef = useRef(null)
    const queryPaneRef = useRef(null)

    const editorSizingLogicProps = {
        editorSceneRef: ref,
        navigatorRef,
        sourceNavigatorResizerProps: {
            containerRef: navigatorRef,
            logicKey: 'source-navigator',
            placement: 'right',
        },
        queryPaneResizerProps: {
            containerRef: queryPaneRef,
            logicKey: 'query-pane',
            placement: 'bottom',
        },
    }

    return (
        <BindLogic logic={editorSizingLogic} props={editorSizingLogicProps}>
            <div className="w-full h-full flex flex-row" ref={ref}>
                <SourceNavigator />
                <QueryTabs />
            </div>
        </BindLogic>
    )
}
