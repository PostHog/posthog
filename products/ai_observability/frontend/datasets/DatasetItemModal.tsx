import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import React from 'react'

import { LemonButton, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'

import { JSONEditor } from '../components/JSONEditor'
import type { DatasetItemModalValue } from './datasetItemModalLogic'
import { DatasetItemModalLogicProps, datasetItemModalLogic, isStoredDatasetItem } from './datasetItemModalLogic'
import { prettifyJson } from './utils'

export interface DatasetItemModalProps {
    isOpen: boolean
    onClose: (refetchDatasetItems?: boolean) => void
    datasetId: string
    partialDatasetItem?: DatasetItemModalValue | null
    /**
     * Whether the modal should display the "Save and add another" button.
     */
    displayBulkCreationButton?: boolean
    title?: string
}

export const DatasetItemModal = React.memo(function DatasetItemModal({
    isOpen,
    onClose,
    partialDatasetItem,
    datasetId,
    displayBulkCreationButton,
    title,
}: DatasetItemModalProps): JSX.Element {
    const logicProps: DatasetItemModalLogicProps = {
        datasetId,
        partialDatasetItem,
        closeModal: onClose,
        isModalOpen: isOpen,
    }
    const { isDatasetItemFormSubmitting, refetchDatasetItems } = useValues(datasetItemModalLogic(logicProps))
    const { submitDatasetItemForm, setShouldCloseModal } = useActions(datasetItemModalLogic(logicProps))

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={() => onClose(refetchDatasetItems)}
            maxWidth="40rem"
            simple
            className="w-full"
        >
            <Form
                logic={datasetItemModalLogic}
                props={logicProps}
                formKey="datasetItemForm"
                enableFormOnSubmit
                className="flex flex-col overflow-y-hidden"
            >
                <LemonModalHeader>
                    <h3>
                        {title ?? (isStoredDatasetItem(partialDatasetItem) ? 'Edit dataset item' : 'New dataset item')}
                    </h3>
                </LemonModalHeader>

                <LemonModalContent className="flex flex-col gap-4">
                    <LemonField name="input" label="Input">
                        <JSONEditor />
                    </LemonField>
                    <LemonField name="expectedOutput" label="Expected output" showOptional>
                        <JSONEditor />
                    </LemonField>
                    {partialDatasetItem?.source_output !== undefined && partialDatasetItem.source_output !== null && (
                        <div>
                            <LemonLabel>Source output</LemonLabel>
                            <JSONEditor value={prettifyJson(partialDatasetItem.source_output) ?? ''} readOnly />
                        </div>
                    )}
                    <LemonField name="metadata" label="Metadata">
                        <JSONEditor />
                    </LemonField>
                </LemonModalContent>

                <LemonModalFooter>
                    {displayBulkCreationButton && !isStoredDatasetItem(partialDatasetItem) && (
                        <LemonButton
                            type="secondary"
                            loading={isDatasetItemFormSubmitting}
                            htmlType="submit"
                            onClick={(e) => {
                                e.preventDefault()
                                setShouldCloseModal(false)
                                submitDatasetItemForm()
                            }}
                        >
                            Save and add another
                        </LemonButton>
                    )}
                    <LemonButton type="primary" htmlType="submit" loading={isDatasetItemFormSubmitting}>
                        Save
                    </LemonButton>
                </LemonModalFooter>
            </Form>
        </LemonModal>
    )
})
