import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FolderSelect } from 'lib/components/FolderSelect/FolderSelect'
import { saveToLogic, SaveToLogicProps } from 'lib/components/SaveTo/saveToLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

const defaultPath = 'Unfiled'

export function SaveToModal(): JSX.Element {
    const { isOpen, form } = useValues(saveToLogic)
    const { closeModal, submitForm } = useActions(saveToLogic)

    const allFolders = splitPath(form.folder || defaultPath)

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            title="Select a folder to save to"
            footer={
                <>
                    <div className="flex-1" />
                    <LemonButton
                        type="primary"
                        onClick={submitForm}
                        tooltip={
                            <>
                                {allFolders.map((pathPart, index) => (
                                    <span key={index}>
                                        {pathPart}
                                        {index < allFolders.length - 1 ? ' / ' : ''}
                                    </span>
                                ))}
                            </>
                        }
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="w-192 max-w-full">
                <Form logic={saveToLogic} formKey="form">
                    <LemonField name="folder">
                        <FolderSelect className="h-[60vh] min-h-[200px]" />
                    </LemonField>
                </Form>
            </div>
        </LemonModal>
    )
}

export interface UseSaveToResponse {
    openModal: () => void
    closeModal: () => void
    SaveToModal: () => JSX.Element
    selectedFolder: string | undefined
}

export function useSaveTo(props: SaveToLogicProps): UseSaveToResponse {
    const { openModal, closeModal } = useActions(saveToLogic(props))
    const { lastNewOperation } = useValues(saveToLogic(props))
    return {
        openModal,
        closeModal,
        SaveToModal: () => (
            <BindLogic logic={saveToLogic} props={props}>
                <SaveToModal />
            </BindLogic>
        ),
        selectedFolder: lastNewOperation?.objectType === props.type ? lastNewOperation?.folder : undefined,
    }
}
