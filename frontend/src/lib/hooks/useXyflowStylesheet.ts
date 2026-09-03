import xyflowStylesheetUrl from '@xyflow/react/dist/style.css?url'

import { useStylesheet } from 'lib/utils/lazyStylesheet'

/** True once the xyflow base stylesheet is attached. Render a `ReactFlow` only when this is true. */
export function useXyflowStylesheet(): boolean {
    return useStylesheet(xyflowStylesheetUrl)
}
