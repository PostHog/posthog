import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FolderSelect } from 'lib/components/FolderSelect/FolderSelect'
import { saveToLogic } from 'lib/components/SaveTo/saveToLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

export function SaveToModal(): JSX.Element {
    const { isOpen, form, isFeatureEnabled } = useValues(saveToLogic)
    const { closeSaveToModal, submitForm } = useActions(saveToLogic)
    const allFolders = splitPath(form.folder || '')

    if (!isFeatureEnabled) {
        return <></>
    }

    return (
        <LemonModal
            onClose={closeSaveToModal}
            isOpen={isOpen}
            title="Select a folder to save to"
            // This is a bit of a hack. Without it, the flow "insight" -> "add to dashboard button" ->
            // "new dashboard template picker modal" -> "save dashboard to modal" wouldn't work.
            // Since SaveToModal is added to the DOM earlier as part of global modals, it's below it in hierarchy.
            zIndex="1169"
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
                        <FolderSelect root="project://" className="h-[60vh] min-h-[200px]" />
                    </LemonField>
                </Form>
            </div>
        </LemonModal>
    )
}
