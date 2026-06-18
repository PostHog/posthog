import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'

// Shared "New folder" affordance for the explorer + tree arms. Prompts for a name and creates the folder
// inside the currently-selected folder (the logic owns the create + refetch).
export function NewFolderButton(): JSX.Element {
    const { createFolder } = useActions(dashboardsFileSystemLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconPlus />}
            data-attr="dashboards-new-folder"
            onClick={() =>
                LemonDialog.openForm({
                    title: 'New folder',
                    initialValues: { folderName: '' },
                    content: (
                        <LemonField name="folderName">
                            <LemonInput placeholder="Enter a folder name" autoFocus />
                        </LemonField>
                    ),
                    errors: {
                        folderName: (name) => (!name?.trim() ? 'You must enter a folder name' : undefined),
                    },
                    onSubmit: ({ folderName }) => createFolder(folderName),
                })
            }
        >
            New folder
        </LemonButton>
    )
}
