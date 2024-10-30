import { IconUpload } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconUploadFile } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'

import { errorTrackingConfigurationSceneLogic } from './errorTrackingConfigurationSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingConfigurationScene,
    logic: errorTrackingConfigurationSceneLogic,
}

export function ErrorTrackingConfigurationScene(): JSX.Element {
    const { missingSymbolSets, missingSymbolSetsLoading } = useValues(errorTrackingConfigurationSceneLogic)
    const { setUploadSymbolSetReference } = useActions(errorTrackingConfigurationSceneLogic)

    return (
        <div>
            <LemonTable
                columns={[
                    { title: 'Reference', dataIndex: 'ref' },
                    {
                        dataIndex: 'ref',
                        width: 154,
                        render: (ref) => {
                            return (
                                <LemonButton
                                    type="primary"
                                    size="xsmall"
                                    icon={<IconUpload />}
                                    onClick={() => setUploadSymbolSetReference(ref || null)}
                                    className="py-1"
                                >
                                    Upload source map
                                </LemonButton>
                            )
                        },
                    },
                ]}
                loading={missingSymbolSetsLoading}
                dataSource={missingSymbolSets}
            />
            <SymbolSetUploadModal onClose={() => setUploadSymbolSetReference(null)} />
        </div>
    )
}

const SymbolSetUploadModal = ({ onClose }: { onClose: () => void }): JSX.Element => {
    const { uploadSymbolSetReference, isUploadSymbolSetSubmitting, uploadSymbolSet } = useValues(
        errorTrackingConfigurationSceneLogic
    )

    return (
        <LemonModal title="" onClose={onClose} isOpen={!!uploadSymbolSetReference} simple>
            <Form
                logic={errorTrackingConfigurationSceneLogic}
                formKey="uploadSymbolSet"
                className="gap-1"
                enableFormOnSubmit
            >
                <LemonModal.Header>
                    <h3>Upload source map</h3>
                </LemonModal.Header>
                <LemonModal.Content className="space-y-2">
                    <LemonField name="files">
                        <LemonFileInput
                            accept="text/plain"
                            multiple={false}
                            callToAction={
                                <div className="flex flex-col items-center justify-center space-y-2 border border-dashed rounded p-4">
                                    <span className="flex items-center gap-2 font-semibold">
                                        <IconUploadFile className="text-2xl" /> Add source map
                                    </span>
                                    <div>
                                        Drag and drop your local source map here or click to open the file browser.
                                    </div>
                                </div>
                            }
                        />
                    </LemonField>
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        disabledReason={uploadSymbolSet.files.length < 1 ? 'Upload a source map' : undefined}
                        type="primary"
                        status="alt"
                        htmlType="submit"
                        loading={isUploadSymbolSetSubmitting}
                    >
                        Upload
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
