import React from 'react'
import { useActions, useValues } from 'kea'
import { pluginSourceLogic } from 'scenes/plugins/edit/pluginSourceLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonRow } from 'lib/components/LemonRow'

export function PluginSourceTabs(): JSX.Element {
    const { setCurrentFile } = useActions(pluginSourceLogic)
    const { currentFile, fileNames, pluginSourceValidationErrors } = useValues(pluginSourceLogic)

    return (
        <LemonRow style={{ padding: 0 }}>
            {fileNames.map((fileName) => (
                <LemonButton
                    key={fileName}
                    type={currentFile === fileName ? 'secondary' : 'tertiary'}
                    onClick={() => setCurrentFile(fileName)}
                    size="small"
                    status={pluginSourceValidationErrors[fileName] ? 'danger' : undefined}
                >
                    {fileName}
                </LemonButton>
            ))}
        </LemonRow>
    )
}
