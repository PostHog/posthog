import { LemonButton, LemonFileInput, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconUploadFile } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { errorTrackingSymbolSetLogic } from './errorTrackingSymbolSetLogic'

export const SymbolSetUploadModal = (): JSX.Element => {
    const { setUploadSymbolSetReference } = useActions(errorTrackingSymbolSetLogic)
    const { uploadSymbolSetReference, isUploadSymbolSetSubmitting, uploadSymbolSet } =
        useValues(errorTrackingSymbolSetLogic)

    const onClose = (): void => setUploadSymbolSetReference(null)

    return (
        <LemonModal title="" onClose={onClose} isOpen={!!uploadSymbolSetReference} simple>
            <Form logic={errorTrackingSymbolSetLogic} formKey="uploadSymbolSet" className="gap-1" enableFormOnSubmit>
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
