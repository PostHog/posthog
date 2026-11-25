import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import type { AccountPropertyConfiguratorProps } from './AccountPropertyConfigurator'
import { QuillAccountPropertySelection } from './QuillAccountPropertySelection'

export function QuillAccountPropertyConfigurator({
    isOpen,
    options,
    pinnedPropertyKeys,
    saving = false,
    onChange,
    onSave,
    onCancel,
    saveDisabledReason,
    title = 'Pin properties',
    resetOptions,
    onReset,
}: AccountPropertyConfiguratorProps): JSX.Element {
    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onCancel()
                }
            }}
        >
            <DialogContent className="sm:max-w-120">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-3">
                        <QuillAccountPropertySelection
                            options={options}
                            selectedKeys={pinnedPropertyKeys}
                            onChange={onChange}
                            saving={saving}
                        />
                        {resetOptions && resetOptions.length > 0 ? (
                            <div className="flex items-center">
                                <DropdownMenu>
                                    <DropdownMenuTrigger
                                        render={
                                            <Button
                                                variant="outline"
                                                disabledReason={saving ? 'Saving' : undefined}
                                                data-attr="account-pinned-properties-reset"
                                            />
                                        }
                                    >
                                        Reset to default
                                        <IconChevronDown />
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="start">
                                        {resetOptions.map((option) => (
                                            <DropdownMenuItem
                                                key={option.key}
                                                onClick={() => {
                                                    if (!saving) {
                                                        onReset?.(option)
                                                    }
                                                }}
                                                data-attr={`account-pinned-properties-reset-${option.key}`}
                                            >
                                                {option.label}
                                            </DropdownMenuItem>
                                        ))}
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </div>
                        ) : null}
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onCancel} data-attr="account-pinned-properties-cancel">
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => onSave(pinnedPropertyKeys)}
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        data-attr="account-pinned-properties-save"
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
