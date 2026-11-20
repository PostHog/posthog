import { Button, Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@posthog/quill'

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
                    <QuillAccountPropertySelection
                        options={options}
                        selectedKeys={pinnedPropertyKeys}
                        onChange={onChange}
                        saving={saving}
                    />
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
