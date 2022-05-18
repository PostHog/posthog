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
import { PluginSourceTabs } from 'scenes/plugins/edit/PluginSourceTabs'

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
    const { isPluginSourceSubmitting, currentFile, pluginSource } = useValues(pluginSourceLogic(logicProps))

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
            title={`Coding Plugin: ${pluginSource.name}`}
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
                        <Field label="The App's Name" name="name">
                            <LemonInput />
                        </Field>

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
