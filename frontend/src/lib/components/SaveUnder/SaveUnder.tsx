import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { saveUnderLogic, SaveUnderLogicProps } from 'lib/components/SaveUnder/saveUnderLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

export function SaveUnderModal(): JSX.Element {
    const { isOpen } = useValues(saveUnderLogic)
    const { closeModal, submitSaveUnder } = useActions(saveUnderLogic)

    return (
        <LemonModal
            onClose={() => {
                closeModal()
            }}
            isOpen={isOpen}
            title="Save to folder"
            footer={
                <>
                    <div className="flex-1">
                        <LemonButton type="primary" onClick={submitSaveUnder}>
                            Save
                        </LemonButton>
                    </div>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
                </>
            }
        >
            <div className="w-192 max-w-full">
                <Form logic={saveUnderLogic} formKey="saveUnder" className="deprecated-space-y-2">
                    <LemonField name="name" label="Name">
                        <LemonInput data-attr="save-under-name" type="text" fullWidth placeholder="Name" />
                    </LemonField>
                    <LemonField name="folder" label="Folder">
                        <LemonInput data-attr="save-under-folder" type="text" fullWidth placeholder="Folder" />
                    </LemonField>
                </Form>
            </div>
        </LemonModal>
    )
}

export function SaveUnder(props: SaveUnderLogicProps): JSX.Element {
    const { openModal } = useActions(saveUnderLogic(props))
    const { folder, objectRef } = props
    const pathParts = splitPath(folder)

    return (
        <BindLogic logic={saveUnderLogic} props={props}>
            <div className="text-xs font-normal text-center mr-1">
                <div className="text-muted">{!objectRef ? 'Save' : 'Saved'} under</div>
                <Tooltip title={folder}>
                    <div className="underline cursor-pointer" onClick={openModal}>
                        {pathParts.length > 0 ? pathParts[pathParts.length - 1] || 'Unfiled' : 'Unfiled'}
                    </div>
                </Tooltip>
                <SaveUnderModal />
            </div>
        </BindLogic>
    )
}
