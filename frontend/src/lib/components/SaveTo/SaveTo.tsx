import { IconCheck, IconChevronRight, IconFolder, IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FolderSelect } from 'lib/components/FolderSelect/FolderSelect'
import { saveToLogic, SelectedFolder } from 'lib/components/SaveTo/saveToLogic'
import { IconBlank } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { useEffect, useState } from 'react'

export function SaveToModal(): JSX.Element {
    const { isOpen, form, selectedFolders, defaultFolder = 'Unfiled' } = useValues(saveToLogic)
    const [showChooseFolder, setShowChooseFolder] = useState(false)
    const [locallySelectedFolder, setLocallySelectedFolder] = useState<SelectedFolder | null>(
        selectedFolders.length > 0 ? selectedFolders[0] : form.folder
    )
    const { closeSaveToModal, submitForm, addSelectedFolder, removeSelectedFolder, setFormValue } =
        useActions(saveToLogic)

    function handleSubmit(): void {
        if (typeof locallySelectedFolder === 'string') {
            addSelectedFolder(locallySelectedFolder)
        }
        setFormValue('folder', locallySelectedFolder)
        setShowChooseFolder(false)
        submitForm()
    }

    useEffect(() => {
        if (typeof form.folder === 'string' && form.folder !== locallySelectedFolder) {
            setLocallySelectedFolder(form.folder)
        }
    }, [form.folder])

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
                    <LemonButton type="primary" onClick={handleSubmit} data-attr="save-to-modal-save-button">
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <div className="flex gap-x-2">
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <ButtonPrimitive fullWidth variant="outline">
                                <IconFolder className="size-4 text-tertiary" />
                                {locallySelectedFolder || 'Project'}
                                {defaultFolder === locallySelectedFolder ? (
                                    <span className="text-tertiary text-xxs pt-[2px]">(Default)</span>
                                ) : null}
                            </ButtonPrimitive>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent className="w-[var(--radix-dropdown-menu-trigger-width)] max-w-[var(--radix-dropdown-menu-trigger-width)]">
                            <DropdownMenuRadioGroup>
                                <DropdownMenuLabel inset>Recent folders</DropdownMenuLabel>
                                <DropdownMenuSeparator />
                                {selectedFolders.length > 0 ? (
                                    selectedFolders.map((folder) => (
                                        <ButtonGroupPrimitive key={folder} menuItem fullWidth>
                                            <DropdownMenuItem asChild>
                                                <ButtonPrimitive
                                                    menuItem
                                                    hasSideActionRight
                                                    active={folder === locallySelectedFolder}
                                                    onClick={() => {
                                                        setLocallySelectedFolder(folder)
                                                    }}
                                                >
                                                    {folder === locallySelectedFolder ? <IconCheck /> : <IconBlank />}
                                                    {folder || 'Project'}
                                                </ButtonPrimitive>
                                            </DropdownMenuItem>
                                            <ButtonPrimitive
                                                iconOnly
                                                isSideActionRight
                                                onClick={() => {
                                                    removeSelectedFolder(folder)
                                                }}
                                                tooltip="Remove folder"
                                                tooltipPlacement="right"
                                            >
                                                <IconTrash />
                                            </ButtonPrimitive>
                                        </ButtonGroupPrimitive>
                                    ))
                                ) : (
                                    <DropdownMenuItem disabled>
                                        <ButtonPrimitive disabled menuItem fullWidth>
                                            <IconBlank />
                                            No recent folders
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                )}

                                <DropdownMenuLabel inset>Default</DropdownMenuLabel>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem asChild>
                                    <ButtonPrimitive
                                        menuItem
                                        hasSideActionRight
                                        active={defaultFolder === locallySelectedFolder}
                                        onClick={() => {
                                            setLocallySelectedFolder(defaultFolder)
                                        }}
                                    >
                                        {defaultFolder === locallySelectedFolder ? <IconCheck /> : <IconBlank />}
                                        {defaultFolder || 'Project'}
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                            </DropdownMenuRadioGroup>
                        </DropdownMenuContent>
                    </DropdownMenu>
                    <ButtonPrimitive
                        variant="outline"
                        onClick={() => setShowChooseFolder(!showChooseFolder)}
                        tooltip="Choose folder from tree"
                        tooltipPlacement="right"
                    >
                        <IconChevronRight className="size-4 text-tertiary rotate-90" />
                    </ButtonPrimitive>
                </div>

                {showChooseFolder && (
                    <div className="max-w-[400px]">
                        <Form logic={saveToLogic} formKey="form">
                            <LemonField name="folder">
                                <FolderSelect
                                    root="project://"
                                    includeRoot
                                    className="h-[60vh] min-h-[200px]"
                                    onChange={setLocallySelectedFolder}
                                    value={locallySelectedFolder || undefined}
                                />
                            </LemonField>
                        </Form>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
