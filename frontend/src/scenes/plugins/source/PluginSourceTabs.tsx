import { BuiltLogic, useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import React from 'react'

import type { pluginSourceLogicType } from './pluginSourceLogicType'

export function PluginSourceTabs({ logic }: { logic: BuiltLogic<pluginSourceLogicType> }): JSX.Element {
    const { setCurrentFile } = useActions(logic)
    const { currentFile, fileNames, pluginSourceAllErrors } = useValues(logic)

    return (
        <div className="flex items-center mb-2 space-x-2 w-full">
            {fileNames.map((fileName) => (
                <React.Fragment key={fileName}>
                    <LemonButton
                        active={currentFile === fileName}
                        onClick={() => setCurrentFile(fileName)}
                        size="small"
                        status={pluginSourceAllErrors[fileName] ? 'danger' : undefined}
                    >
                        {fileName}
                    </LemonButton>
                </React.Fragment>
            ))}
        </div>
    )
}
