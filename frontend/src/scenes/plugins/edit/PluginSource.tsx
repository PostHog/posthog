import React from 'react'
import { useActions, useValues } from 'kea'
import { Button } from 'antd'
import MonacoEditor from '@monaco-editor/react'
import { Drawer } from 'lib/components/Drawer'

import { userLogic } from 'scenes/userLogic'
import { canGloballyManagePlugins } from '../access'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
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
    const { user } = useValues(userLogic)
    const { submitPlugin } = useActions(pluginSourceLogic({ id }))
    const { isPluginSubmitting, pluginChanged, plugin } = useValues(pluginSourceLogic({ id }))
    const { featureFlags } = useValues(featureFlagLogic)

    if (!canGloballyManagePlugins(user?.organization)) {
        return null
    }

    // function addReactSupport(monaco: any): void {
    //     monaco.languages.typescript.typescriptDefaults.setCompilerOptions({
    //         jsx: 'react',
    //     })
    // }

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
                        <Field label="Source Code" name="source">
                            <MonacoEditor
                                language="typescript"
                                path="source.ts"
                                theme="vs-dark"
                                height={700}
                                options={{
                                    minimap: { enabled: false },
                                }}
                            />
                        </Field>
                        {featureFlags[FEATURE_FLAGS.FRONTEND_APPS] ? (
                            <Field label="Frontend TSX" name="source_frontend">
                                <MonacoEditor
                                    language="typescript"
                                    path="frontend.tsx"
                                    theme="vs-dark"
                                    // beforeMount={addReactSupport}
                                    height={700}
                                    options={{
                                        minimap: { enabled: false },
                                    }}
                                />
                            </Field>
                        ) : null}
                        <Field label="Config Schema JSON" name="config_schema">
                            <MonacoEditor path="config.json" language="json" theme="vs-dark" height={200} />
                        </Field>
                    </>
                ) : null}
            </VerticalForm>
        </Drawer>
    )
}
