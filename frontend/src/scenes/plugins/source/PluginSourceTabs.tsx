import React from 'react'
import { BuiltLogic, useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import type { pluginSourceLogicType } from './pluginSourceLogicType'
import { IconPlus } from 'lib/components/icons'

export function PluginSourceTabs({ logic }: { logic: BuiltLogic<pluginSourceLogicType> }): JSX.Element {
    const { setCurrentFile, addFilePrompt } = useActions(logic)
    const { currentFile, fileNames, pluginSourceAllErrors } = useValues(logic)

    return (
        <div className="flex items-center justify-between mb-2 space-x-2 w-full">
            <div className="flex items-center space-x-2">
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
            <LemonButton onClick={addFilePrompt} icon={<IconPlus />}>
                Add File
            </LemonButton>
        </div>
    )
}
