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
    Text,
} from '@posthog/quill'

import { WarehouseCopyButton } from '../WarehouseConnectScene/WarehouseCopyButton'
import { warehouseLoginsLogic } from './warehouseLoginsLogic'

export function WarehouseRevealedPasswordDialog(): JSX.Element {
    const { activeReveal: revealedPassword } = useValues(warehouseLoginsLogic)
    const { closeReveal } = useActions(warehouseLoginsLogic)

    return (
        <Dialog
            open={revealedPassword !== null}
            disablePointerDismissal
            // Only "I saved it" closes it. A stray click or Escape would drop a password that cannot be shown again.
            onOpenChange={(open, details) => {
                if (!open && details?.reason === 'close-press') {
                    closeReveal()
                }
            }}
        >
            <DialogContent showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>
                        {revealedPassword?.reason === 'created' ? 'Login created' : 'New password'}
                    </DialogTitle>
                    <DialogDescription>You won't see this password again. Copy it and keep it safe.</DialogDescription>
                </DialogHeader>
                <DialogBody className="flex flex-col gap-3">
                    <div>
                        <Text size="xs" variant="muted" render={<div />}>
                            Username
                        </Text>
                        <Text size="sm" className="block break-all font-mono" render={<code />}>
                            {revealedPassword?.username}
                        </Text>
                    </div>
                    <div className="flex items-center justify-between gap-2 rounded-md border px-3 py-2">
                        <div className="min-w-0">
                            <Text size="xs" variant="muted" render={<div />}>
                                Password
                            </Text>
                            <Text size="sm" className="ph-no-capture block break-all font-mono" render={<code />}>
                                {revealedPassword?.password}
                            </Text>
                        </div>
                        {revealedPassword && (
                            <WarehouseCopyButton
                                iconOnly
                                value={revealedPassword.password}
                                thing="password"
                                target="login_password"
                            />
                        )}
                    </div>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="primary" />}>I saved it</DialogClose>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
