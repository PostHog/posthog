import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Label,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import type { LoginModeEnumApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { warehouseLoginsLogic } from './warehouseLoginsLogic'

export function WarehouseNewLoginDialog(): JSX.Element {
    const { newLoginOpen, newLoginMode, effectiveNewLoginTeamId, projects, isCreating, existingLogin } =
        useValues(warehouseLoginsLogic)
    const { closeNewLogin, setNewLoginTeamId, setNewLoginMode, createLogin } = useActions(warehouseLoginsLogic)
    const items = projects.map((project) => ({ label: project.name, value: project.id }))

    return (
        <Dialog
            open={newLoginOpen}
            onOpenChange={(open) => {
                if (!open && !isCreating) {
                    closeNewLogin()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>New login</DialogTitle>
                    <DialogDescription>
                        A project login can query that project's tables through Trino.
                        {existingLogin
                            ? ` This project already has a login with this access. Its current password stops working when you rotate it.`
                            : ''}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody className="flex flex-col gap-4">
                    <div className="flex flex-col gap-1">
                        <Label>Project</Label>
                        <Select
                            items={items}
                            value={effectiveNewLoginTeamId}
                            onValueChange={(value) => typeof value === 'number' && setNewLoginTeamId(value)}
                        >
                            <SelectTrigger className="w-full">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {items.map((item) => (
                                    <SelectItem key={item.value} value={item.value}>
                                        {item.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="flex flex-col gap-1">
                        <Label>Access</Label>
                        <RadioGroup
                            value={newLoginMode}
                            onValueChange={(value) => setNewLoginMode(value as LoginModeEnumApi)}
                        >
                            <div className="flex items-center gap-2">
                                <RadioGroupItem value="reader" id="new-login-reader" />
                                <Label htmlFor="new-login-reader">Read only</Label>
                            </div>
                            <div className="flex items-center gap-2">
                                <RadioGroupItem value="user" id="new-login-user" />
                                <Label htmlFor="new-login-user">Read and write</Label>
                            </div>
                        </RadioGroup>
                        <Text size="xs" variant="muted">
                            Read only can only read the project's data. Read and write can also write to it.
                        </Text>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                    <Button
                        variant="primary"
                        loading={isCreating}
                        disabled={effectiveNewLoginTeamId === null}
                        onClick={() => createLogin()}
                        data-attr="warehouse-access-login-create"
                    >
                        {existingLogin ? 'Rotate password' : 'Create login'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
