import './PluginSource.scss'

import { useMonaco } from '@monaco-editor/react'
import { Link } from '@posthog/lemon-ui'
import { Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { CodeEditor } from 'lib/components/CodeEditors'
import { Drawer } from 'lib/components/Drawer'
import { Field } from 'lib/forms/Field'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useEffect } from 'react'
import { createDefaultPluginSource } from 'scenes/plugins/source/createDefaultPluginSource'
import { pluginSourceLogic } from 'scenes/plugins/source/pluginSourceLogic'
import { PluginSourceTabs } from 'scenes/plugins/source/PluginSourceTabs'
import { userLogic } from 'scenes/userLogic'

import { canGloballyManagePlugins } from '../access'

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
    const logic = pluginSourceLogic(logicProps)
    const { submitPluginSource, closePluginSource } = useActions(logic)
    const { isPluginSourceSubmitting, pluginSourceLoading, currentFile, name } = useValues(
        pluginSourceLogic(logicProps)
    )

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.typescript.typescriptDefaults.setCompilerOptions({
            jsx: currentFile.endsWith('.tsx')
                ? monaco.languages.typescript.JsxEmit.React
                : monaco.languages.typescript.JsxEmit.Preserve,
            esModuleInterop: true,
        })
    }, [monaco, currentFile])

    useEffect(() => {
        if (!monaco) {
            return
        }
        void import('./types/packages.json').then((files) => {
            for (const [fileName, fileContents] of Object.entries(files).filter(
                ([fileName]) => fileName !== 'default'
            )) {
                const fakePath = `file:///node_modules/${fileName}`
                monaco?.languages.typescript.typescriptDefaults.addExtraLib(fileContents as string, fakePath)
            }
        })
    }, [monaco])

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
                <div className="text-right space-x-2">
                    <LemonButton onClick={closePluginSource}>Close</LemonButton>
                    <LemonButton type="primary" loading={isPluginSourceSubmitting} onClick={submitPluginSource}>
                        Save
                    </LemonButton>
                </div>
            }
        >
            <Form logic={pluginSourceLogic} props={logicProps} formKey="pluginSource" className="PluginSource">
                {visible ? (
                    <>
                        <p>
                            Read our{' '}
                            <Link to="https://posthog.com/docs/apps/build" target="_blank">
                                app building overview in PostHog Docs
                            </Link>{' '}
                            for a good grasp of possibilities.
                            <br />
                            Once satisfied with your app, feel free to{' '}
                            <Link to="https://posthog.com/docs/apps/build/tutorial#submitting-your-app" target="_blank">
                                submit it to the official App Store
                            </Link>
                            .
                        </p>

                        {pluginSourceLoading ? (
                            <Skeleton />
                        ) : (
                            <>
                                <PluginSourceTabs logic={logic} />
                                <Field name={[currentFile]}>
                                    {({ value, onChange }) => (
                                        <>
                                            <CodeEditor
                                                path={currentFile}
                                                language={currentFile.endsWith('.json') ? 'json' : 'typescript'}
                                                value={value}
                                                onChange={(v) => onChange(v ?? '')}
                                                height={700}
                                                options={{
                                                    minimap: { enabled: false },
                                                }}
                                            />
                                            {!value && createDefaultPluginSource(name)[currentFile] ? (
                                                <div className="mt-2">
                                                    <LemonButton
                                                        type="primary"
                                                        onClick={() =>
                                                            onChange(createDefaultPluginSource(name)[currentFile])
                                                        }
                                                    >
                                                        Add example "{currentFile}"
                                                    </LemonButton>
                                                </div>
                                            ) : null}
                                        </>
                                    )}
                                </Field>
                            </>
                        )}
                    </>
                ) : null}
            </Form>
        </Drawer>
    )
}
