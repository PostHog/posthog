import './PluginSource.scss'
import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { Button, Skeleton } from 'antd'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { Drawer } from 'lib/components/Drawer'

import { userLogic } from 'scenes/userLogic'
import { canGloballyManagePlugins } from '../access'
import { pluginSourceLogic } from 'scenes/plugins/source/pluginSourceLogic'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field } from 'lib/forms/Field'
import { PluginSourceTabs } from 'scenes/plugins/source/PluginSourceTabs'

interface PluginSourceProps {
    pluginId: number
    pluginConfigId?: number
    visible: boolean
    close: () => void
    placement?: 'top' | 'right' | 'bottom' | 'left'
}

export function PluginSource({
    pluginId,
    pluginConfigId,
    visible,
    close,
    placement,
}: PluginSourceProps): JSX.Element | null {
    const monaco = useMonaco()
    const { user } = useValues(userLogic)

    const logicProps = { pluginId, pluginConfigId, onClose: close }
    const { submitPluginSource, closePluginSource } = useActions(pluginSourceLogic(logicProps))
    const { isPluginSourceSubmitting, pluginSourceLoading, currentFile, name } = useValues(
        pluginSourceLogic(logicProps)
    )

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
            title={pluginSourceLoading ? 'Loading...' : `Edit App: ${name}`}
            placement={placement ?? 'left'}
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
            <VerticalForm logic={pluginSourceLogic} props={logicProps} formKey="pluginSource" className="PluginSource">
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

                        {pluginSourceLoading ? (
                            <Skeleton />
                        ) : (
                            <>
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
                        )}
                    </>
                ) : null}
            </VerticalForm>
        </Drawer>
    )
}
