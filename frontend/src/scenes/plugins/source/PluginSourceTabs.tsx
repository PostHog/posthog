import React from 'react'
import { BuiltLogic, useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import type { pluginSourceLogicType } from './pluginSourceLogicType'

export function PluginSourceTabs({ logic }: { logic: BuiltLogic<pluginSourceLogicType> }): JSX.Element {
    const { setCurrentFile } = useActions(logic)
    const { currentFile, fileNames, pluginSourceAllErrors } = useValues(logic)

    return (
        <div className="flex items-center mb-2" style={{ gap: '0.5rem' }}>
            {fileNames.map((fileName) => (
                <LemonButton
                    key={fileName}
                    active={currentFile === fileName}
                    onClick={() => setCurrentFile(fileName)}
                    size="small"
                    status={pluginSourceAllErrors[fileName] ? 'danger' : undefined}
                >
                    {fileName}
                </LemonButton>
            ))}
        </div>
    )
}
