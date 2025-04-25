import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FolderSelect } from 'lib/components/FolderSelect/FolderSelect'
import { saveUnderLogic, SaveUnderLogicProps } from 'lib/components/SaveUnder/saveUnderLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

const defaultPath = 'Unfiled'

export function SaveUnderModal(): JSX.Element {
    const { isOpen, form } = useValues(saveUnderLogic)
    const { closeModal, submitForm } = useActions(saveUnderLogic)

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
                <Form logic={saveUnderLogic} formKey="form">
                    <LemonField name="folder">
                        <FolderSelect className="h-[60vh] min-h-[200px]" />
                    </LemonField>
                </Form>
            </div>
        </LemonModal>
    )
}

export interface UseSaveUnderResponse {
    openModal: () => void
    closeModal: () => void
    SaveUnderModal: () => JSX.Element
    selectedFolder: string | undefined
}

export function useSaveUnder(props: SaveUnderLogicProps): UseSaveUnderResponse {
    const { openModal, closeModal } = useActions(saveUnderLogic(props))
    const { lastNewOperation } = useValues(saveUnderLogic(props))
    return {
        openModal,
        closeModal,
        SaveUnderModal: () => (
            <BindLogic logic={saveUnderLogic} props={props}>
                <SaveUnderModal />
            </BindLogic>
        ),
        selectedFolder: lastNewOperation?.objectType === props.type ? lastNewOperation?.folder : undefined,
    }
}
