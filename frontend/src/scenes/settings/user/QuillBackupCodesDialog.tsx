import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Text,
} from '@posthog/quill'

import { twoFactorLogic } from 'scenes/authentication/two-factor-setup/twoFactorLogic'

export function QuillBackupCodesDialog({ onCopyBackupCodes }: { onCopyBackupCodes: () => void }): JSX.Element {
    const { status, isBackupCodesModalOpen, generatingCodes, generatingCodesLoading } = useValues(twoFactorLogic)
    const { generateBackupCodes, toggleBackupCodesModal } = useActions(twoFactorLogic)

    const backupCodesRemaining = status?.backup_codes_remaining

    return (
        <Dialog
            open={isBackupCodesModalOpen}
            onOpenChange={(nextOpen: boolean) => !nextOpen && toggleBackupCodesModal(false)}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Backup codes</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        {generatingCodes?.backup_codes.length ? (
                            <>
                                <Text size="xs" render={<p className="m-0" />}>
                                    Save these backup codes in a secure location. Each code can only be used once to
                                    sign in if you lose access to your authentication device. You won't be able to see
                                    them again after you close this window.
                                </Text>
                                <div className="ph-no-capture ph-replay-block flex items-start justify-between gap-2 rounded-md bg-muted p-4">
                                    <div className="flex flex-col gap-1 font-mono text-xs" translate="no">
                                        {generatingCodes.backup_codes.map((code) => (
                                            <span key={code}>{code}</span>
                                        ))}
                                    </div>
                                    <Button variant="outline" onClick={onCopyBackupCodes}>
                                        <IconCopy />
                                        Copy
                                    </Button>
                                </div>
                            </>
                        ) : (
                            <Text size="xs" render={<p className="m-0" />}>
                                {backupCodesRemaining
                                    ? `You have ${backupCodesRemaining} unused backup ${backupCodesRemaining === 1 ? 'code' : 'codes'}. Backup codes are only shown once, when you generate them. Generate new codes to replace them.`
                                    : "You don't have any unused backup codes. Generate codes to sign in if you lose access to your authentication device."}
                            </Text>
                        )}
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="primary" onClick={() => generateBackupCodes()} loading={generatingCodesLoading}>
                        {backupCodesRemaining ? 'Generate new codes' : 'Generate backup codes'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
