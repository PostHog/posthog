import { LemonBanner, LemonButton, LemonModal, LemonTabs, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { CodeEditor } from 'lib/components/CodeEditors'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { PluginInstallationType } from '~/types'

import { appsCodeLogic } from './appCodeLogic'
import { appsManagementLogic } from './appsManagementLogic'

export function AppCode({
    pluginId,
    pluginType,
}: {
    pluginId: number
    pluginType: PluginInstallationType
}): JSX.Element {
    const logicProps = { pluginId }
    const logic = appsCodeLogic(logicProps)
    const {
        currentFile,
        filenames,
        pluginSource,
        pluginSourceLoading,
        editingAppCode,
        pluginSourceAllErrors,
        pluginSourceHasErrors,
        isPluginSourceSubmitting,
    } = useValues(logic)
    const { setCurrentFile, cancelEditing, editAppCode, submitPluginSource } = useActions(logic)
    const { canGloballyManagePlugins, plugins } = useValues(appsManagementLogic)

    if (pluginSourceLoading) {
        return <Spinner />
    }

    const canEdit = canGloballyManagePlugins && pluginType === PluginInstallationType.Source

    return (
        <>
            <LemonModal
                onClose={cancelEditing}
                isOpen={editingAppCode}
                width={600}
                title={'Edit ' + plugins[pluginId].name + ' source code'}
                description={
                    <p>
                        Read our{' '}
                        <Link to="https://posthog.com/docs/apps/build" target="_blank">
                            app building overview in PostHog Docs
                        </Link>{' '}
                        for a good grasp of possibilities.
                    </p>
                }
                footer={
                    <>
                        <LemonButton type="secondary" onClick={cancelEditing}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            loading={isPluginSourceSubmitting}
                            type="primary"
                            onClick={() => submitPluginSource()}
                        >
                            Save
                        </LemonButton>
                    </>
                }
            >
                <Form logic={appsCodeLogic} props={logicProps} formKey="pluginSource">
                    {canEdit ? (
                        <>
                            {pluginSourceLoading ? (
                                <Spinner />
                            ) : (
                                <>
                                    <LemonTabs
                                        activeKey={currentFile}
                                        onChange={(filename) => setCurrentFile(filename)}
                                        tabs={Object.values(filenames).map((filename) => ({
                                            label: filename,
                                            key: filename,
                                            content: (
                                                <>
                                                    {pluginSourceHasErrors && (
                                                        <LemonBanner type={'error'}>
                                                            {JSON.stringify(pluginSourceAllErrors)}
                                                        </LemonBanner>
                                                    )}
                                                    <Field name={[currentFile]}>
                                                        {({ value, onChange }) => (
                                                            <>
                                                                <CodeEditor
                                                                    path={currentFile}
                                                                    language={
                                                                        currentFile.endsWith('.json')
                                                                            ? 'json'
                                                                            : 'typescript'
                                                                    }
                                                                    value={value}
                                                                    onChange={(v) => onChange(v ?? '')}
                                                                    height={700}
                                                                    options={{
                                                                        minimap: { enabled: false },
                                                                    }}
                                                                />
                                                            </>
                                                        )}
                                                    </Field>
                                                </>
                                            ),
                                        }))}
                                    />
                                </>
                            )}
                        </>
                    ) : null}
                </Form>
            </LemonModal>

            <LemonTabs
                activeKey={currentFile}
                onChange={(filename) => setCurrentFile(filename)}
                tabs={Object.values(filenames).map((filename) => ({
                    label: filename,
                    key: filename,
                    content: (
                        <>
                            {canEdit && (
                                <div className="flex items-center gap-2">
                                    <LemonButton type="secondary" onClick={() => editAppCode()}>
                                        Edit
                                    </LemonButton>
                                </div>
                            )}
                            {
                                <CodeSnippet
                                    language={currentFile.endsWith('.json') ? Language.JSON : Language.JavaScript}
                                    thing={currentFile}
                                    maxLinesWithoutExpansion={20}
                                    style={{ fontSize: 12 }}
                                    wrap
                                >
                                    {pluginSource[currentFile] ?? ''}
                                </CodeSnippet>
                            }
                        </>
                    ),
                }))}
            />
        </>
    )
}
