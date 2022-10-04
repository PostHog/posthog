import React from 'react'
import { BuiltLogic, useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import type { pluginSourceLogicType } from './pluginSourceLogicType'
import { IconDelete, IconPlus } from 'lib/components/icons'

export function PluginSourceTabs({ logic }: { logic: BuiltLogic<pluginSourceLogicType> }): JSX.Element {
    const { setCurrentFile, addFilePrompt, removeSourceFile } = useActions(logic)
    const { currentFile, fileNames, pluginSourceAllErrors } = useValues(logic)

    return (
        <div className="flex items-center justify-between mb-2 space-x-2 w-full">
            <div className="flex items-center space-x-2">
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
            <div className="flex items-center space-x-2">
                <LemonButton onClick={addFilePrompt} icon={<IconPlus />} size="small">
                    Add new file
                </LemonButton>
                {currentFile !== 'plugin.json' ? (
                    <LemonButton
                        onClick={() => removeSourceFile(currentFile)}
                        icon={<IconDelete />}
                        size="small"
                        status="danger"
                    >
                        Delete "{currentFile}"
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )
}
