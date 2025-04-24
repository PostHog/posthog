import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FolderSelect } from 'lib/components/FolderSelect/FolderSelect'
import { saveUnderLogic, SaveUnderLogicProps } from 'lib/components/SaveUnder/saveUnderLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

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
            title="Select a folder to save in"
            footer={
                <>
                    <div className="flex-1 flex gap-2 items-center">
                        <LemonButton type="secondary" onClick={closeModal}>
                            Close
                        </LemonButton>
                    </div>
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

export function SaveUnder(props: SaveUnderLogicProps): JSX.Element {
    const { openModal } = useActions(saveUnderLogic(props))
    const { form, lastNewOperation } = useValues(saveUnderLogic(props))
    const { objectRef, defaultFolder } = props
    const actualFolder = lastNewOperation?.folder || form.folder || defaultFolder || defaultPath
    const pathParts = splitPath(actualFolder)
    const lastPath = pathParts.length > 0 ? pathParts[pathParts.length - 1] || defaultPath : defaultPath

    return (
        <BindLogic logic={saveUnderLogic} props={props}>
            <div className="text-xs font-normal text-center mr-1">
                <div className="text-muted">{!objectRef ? 'Save' : 'Saved'} under</div>
                <Tooltip
                    title={
                        <>
                            {pathParts.map((pathPart, index) => (
                                <span key={index}>
                                    {pathPart}
                                    {index < pathParts.length - 1 ? ' / ' : ''}
                                </span>
                            ))}
                        </>
                    }
                >
                    <div className="underline cursor-pointer" onClick={openModal}>
                        {lastPath}
                    </div>
                </Tooltip>
            </div>
            <SaveUnderModal />
        </BindLogic>
    )
}
