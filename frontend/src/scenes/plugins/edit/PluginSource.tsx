import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { Button } from 'antd'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { Drawer } from 'lib/components/Drawer'

import { userLogic } from 'scenes/userLogic'
import { canGloballyManagePlugins } from '../access'
import { pluginSourceLogic } from 'scenes/plugins/edit/pluginSourceLogic'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'

interface PluginSourceProps {
    id: number
    visible: boolean
    close: () => void
}

export function PluginSource({ id, visible, close }: PluginSourceProps): JSX.Element | null {
    const monaco = useMonaco()
    const { user } = useValues(userLogic)
    const { submitPlugin, setFile, setActiveFileValue } = useActions(pluginSourceLogic({ id }))
    const { isPluginSubmitting, pluginChanged, plugin, files, activeFile } = useValues(pluginSourceLogic({ id }))

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.typescript.typescriptDefaults.setCompilerOptions({
            jsx: activeFile?.name.endsWith('.tsx') ? 'react' : 'preserve',
        })
    }, [monaco, activeFile?.name])

    if (!canGloballyManagePlugins(user?.organization)) {
        return null
    }

    return (
        <Drawer
            forceRender={true}
            visible={visible}
            onClose={() => {
                if (pluginChanged) {
                    confirm('You have unsaved changes in your plugin. Are you sure you want to exit?') && close()
                } else {
                    close()
                }
            }}
            width={'min(90vw, 64rem)'}
            title={`Coding Plugin: ${plugin.name}`}
            placement="left"
            footer={
                <div style={{ textAlign: 'right' }}>
                    <Button onClick={() => close()} style={{ marginRight: 16 }}>
                        Cancel
                    </Button>
                    <Button type="primary" loading={isPluginSubmitting} onClick={submitPlugin}>
                        Save
                    </Button>
                </div>
            }
        >
            <VerticalForm logic={pluginSourceLogic} props={{ id }} formKey="plugin">
                {visible ? (
                    <>
                        <p>
                            Read our{' '}
                            <a href="https://posthog.com/docs/plugins/build/overview" target="_blank">
                                plugin building overview in PostHog Docs
                            </a>{' '}
                            for a good grasp of possibilities.
                            <br />
                            Once satisfied with your plugin, feel free to{' '}
                            <a
                                href="https://posthog.com/docs/plugins/build/tutorial#submitting-your-plugin"
                                target="_blank"
                            >
                                submit it to the official Plugin Library
                            </a>
                            .
                        </p>
                        <Field label="Name" name="name">
                            <LemonInput />
                        </Field>

                        {Object.values(files).map((file) => (
                            <button
                                key={file.name}
                                disabled={activeFile?.name === file.name}
                                onClick={() => setFile(file.name)}
                                style={{ fontWeight: activeFile?.name === file.name ? 'bold' : 'normal' }}
                            >
                                {file.name}
                            </button>
                        ))}

                        <MonacoEditor
                            theme="vs-dark"
                            path={activeFile.name}
                            language={activeFile.language}
                            value={activeFile.value}
                            onChange={(v) => setActiveFileValue(v ?? '')}
                            height={700}
                            options={{
                                minimap: { enabled: false },
                            }}
                        />
                    </>
                ) : null}
            </VerticalForm>
        </Drawer>
    )
}
