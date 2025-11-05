import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonSnack } from '@posthog/lemon-ui'

import { FolderSelect } from 'lib/components/FileSystem/FolderSelect/FolderSelect'
import { linkToLogic } from 'lib/components/FileSystem/LinkTo/linkToLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

export function LinkToModal(): JSX.Element {
    const { isOpen, form, linkingItems } = useValues(linkToLogic)
    const { closeLinkToModal, submitForm } = useActions(linkToLogic)

    const destinationFolder = form.folder || 'Project root'
    const allFolders = splitPath(destinationFolder)
    const lastFolder = allFolders[allFolders.length - 1]

    const s = linkingItems.length === 1 ? '' : 's'

    return (
        <LemonModal
            onClose={closeLinkToModal}
            isOpen={isOpen}
            title={`Select a folder to create shortcut${s} in`}
            description={
                <>
                    You are creating {linkingItems.length} shortcut{s} in <LemonSnack>{destinationFolder}</LemonSnack>
                </>
            }
            // This is a bit of a hack. Without it, the flow "insight" -> "add to dashboard button" ->
            // "new dashboard template picker modal" -> "save dashboard to modal" wouldn't work.
            // Since LinkToModal is added to the DOM earlier as part of global modals, it's below it in hierarchy.
            zIndex="1169"
            footer={
                <>
                    <div className="flex-1" />
                    <LemonButton
                        type="primary"
                        onClick={submitForm}
                        data-attr="link-to-modal-move-button"
                        disabledReason={typeof lastFolder !== 'string' ? 'Please select a folder' : undefined}
                    >
                        Create shortcut{s} in {lastFolder}
                    </LemonButton>
                </>
            }
        >
            <div className="w-192 max-w-full">
                <Form logic={linkToLogic} formKey="form">
                    <LemonField name="folder">
                        <FolderSelect root="project://" includeRoot className="h-[60vh] min-h-[200px]" />
                    </LemonField>
                </Form>
            </div>
        </LemonModal>
    )
}
