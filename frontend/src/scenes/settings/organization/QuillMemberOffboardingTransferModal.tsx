import { useActions, useValues } from 'kea'

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

import { MemberSelect } from 'lib/components/MemberSelect'

import { memberOffboardingLogic } from './memberOffboardingLogic'

export function QuillMemberOffboardingTransferModal(): JSX.Element {
    const { member, transferIds, transferOwner, savingResourcesLoading, getSelectionLabel } =
        useValues(memberOffboardingLogic)
    const { closeTransfer, setTransferOwner, transferOwnership } = useActions(memberOffboardingLogic)
    const disabledReason = savingResourcesLoading ? 'Transferring ownership…' : undefined

    return (
        <Dialog
            open={transferIds.length > 0}
            onOpenChange={(open) => {
                if (!open && !disabledReason) {
                    closeTransfer()
                }
            }}
        >
            <DialogContent showCloseButton={!disabledReason}>
                <DialogHeader>
                    <DialogTitle>Transfer ownership</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-3">
                        <Text size="xs" render={<p className="m-0" />}>
                            {`Transfer ${getSelectionLabel(transferIds)} to another organization member. They will be enabled and run with the new owner's access.`}
                        </Text>
                        <MemberSelect
                            value={transferOwner?.uuid ?? null}
                            onChange={setTransferOwner}
                            excludedMembers={member ? [member.user.uuid] : []}
                            allowNone={false}
                            defaultLabel="Choose a new owner"
                        />
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            The new owner must have access to each project and the data it uses. Recipients stay the
                            same.
                        </Text>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeTransfer} disabledReason={disabledReason}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={savingResourcesLoading}
                        onClick={transferOwnership}
                        disabledReason={!transferOwner ? 'Choose a new owner.' : undefined}
                    >
                        Transfer
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
