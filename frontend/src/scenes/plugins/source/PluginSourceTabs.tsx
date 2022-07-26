import React from 'react'
import { useActions, useValues } from 'kea'
import { pluginSourceLogic } from 'scenes/plugins/source/pluginSourceLogic'
import { LemonButton } from 'lib/components/LemonButton'

export function PluginSourceTabs(): JSX.Element {
    const { setCurrentFile } = useActions(pluginSourceLogic)
    const { currentFile, fileNames, pluginSourceAllErrors } = useValues(pluginSourceLogic)

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
