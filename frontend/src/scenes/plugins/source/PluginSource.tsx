import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { Button } from 'antd'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { Drawer } from 'lib/components/Drawer'

import { userLogic } from 'scenes/userLogic'
import { canGloballyManagePlugins } from '../access'
import { pluginSourceLogic } from 'scenes/plugins/source/pluginSourceLogic'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field } from 'lib/forms/Field'
import { PluginSourceTabs } from 'scenes/plugins/source/PluginSourceTabs'

interface PluginSourceProps {
    id: number
    visible: boolean
    close: () => void
}

export function PluginSource({ id, visible, close }: PluginSourceProps): JSX.Element | null {
    const monaco = useMonaco()
    const { user } = useValues(userLogic)

    const logicProps = { id, onClose: close }
    const { submitPluginSource, closePluginSource } = useActions(pluginSourceLogic(logicProps))
    const { isPluginSourceSubmitting, currentFile, name } = useValues(pluginSourceLogic(logicProps))

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.typescript.typescriptDefaults.setCompilerOptions({
            jsx: currentFile.endsWith('.tsx') ? 'react' : 'preserve',
        })
    }, [monaco, currentFile])

    if (!canGloballyManagePlugins(user?.organization)) {
        return null
    }

    return (
        <Drawer
            forceRender={true}
            visible={visible}
            onClose={closePluginSource}
            width={'min(90vw, 64rem)'}
            title={`Coding Plugin: ${name}`}
            placement="left"
            footer={
                <div style={{ textAlign: 'right' }}>
                    <Button onClick={closePluginSource} style={{ marginRight: 16 }}>
                        Close
                    </Button>
                    <Button type="primary" loading={isPluginSourceSubmitting} onClick={submitPluginSource}>
                        Save
                    </Button>
                </div>
            }
        >
            <VerticalForm logic={pluginSourceLogic} props={logicProps} formKey="pluginSource">
                {visible ? (
                    <>
                        <p>
                            Read our{' '}
                            <a href="https://posthog.com/docs/apps/build" target="_blank">
                                app building overview in PostHog Docs
                            </a>{' '}
                            for a good grasp of possibilities.
                            <br />
                            Once satisfied with your app, feel free to{' '}
                            <a href="https://posthog.com/docs/apps/build/tutorial#submitting-your-app" target="_blank">
                                submit it to the official App Store
                            </a>
                            .
                        </p>

                        <PluginSourceTabs />

                        <Field name={[currentFile]}>
                            {({ value, onChange }) => (
                                <MonacoEditor
                                    theme="vs-dark"
                                    path={currentFile}
                                    language={currentFile.endsWith('.json') ? 'json' : 'typescript'}
                                    value={value}
                                    onChange={(v) => onChange(v ?? '')}
                                    height={700}
                                    options={{
                                        minimap: { enabled: false },
                                    }}
                                />
                            )}
                        </Field>
                    </>
                ) : null}
            </VerticalForm>
        </Drawer>
    )
}
