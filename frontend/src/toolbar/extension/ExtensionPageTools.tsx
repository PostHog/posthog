import { useMountedLogic } from 'kea'

import { ExtensionElementSelector } from './ExtensionElementSelector'
import { ExtensionFlagOverrides } from './ExtensionFlagOverrides'
import { ExtensionHeatmapControl } from './ExtensionHeatmapControl'
import { extensionPageToolsLogic } from './extensionPageToolsLogic'

export function ExtensionPageTools(): JSX.Element {
    useMountedLogic(extensionPageToolsLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="text-secondary text-xs">On this page</div>
            <ExtensionHeatmapControl />
            <ExtensionElementSelector />
            <ExtensionFlagOverrides />
        </div>
    )
}
