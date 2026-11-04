import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { fullNameOrEmail } from 'lib/utils/strings'

import { memberOffboardingLogic } from './memberOffboardingLogic'

export function MemberOffboardingTransferModal(): JSX.Element {
    const { member, transferIds, transferOwner, savingResourcesLoading, getSelectionLabel } =
        useValues(memberOffboardingLogic)
    const { closeTransfer, setTransferOwner, transferOwnership } = useActions(memberOffboardingLogic)

    return (
        <LemonModal
            isOpen={transferIds.length > 0}
            onClose={savingResourcesLoading ? undefined : closeTransfer}
            title="Transfer ownership"
            width={480}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeTransfer}
                        disabledReason={savingResourcesLoading ? 'Transferring ownership…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={savingResourcesLoading}
                        onClick={transferOwnership}
                        disabledReason={!transferOwner ? 'Choose a new owner.' : undefined}
                    >
                        Transfer and enable
                    </LemonButton>
                </>
            }
        >
            <p>{`Transfer ${getSelectionLabel(transferIds)} to another organization member. They will be enabled and run with the new owner's access.`}</p>
            <MemberSelect
                value={transferOwner?.uuid ?? null}
                onChange={setTransferOwner}
                excludedMembers={member ? [member.user.uuid] : []}
                allowNone={false}
                defaultLabel={transferOwner ? fullNameOrEmail(transferOwner) : 'Choose a new owner'}
            >
                {() => (
                    <LemonButton
                        type="secondary"
                        disabledReason={savingResourcesLoading ? 'Transferring ownership…' : undefined}
                    >
                        {transferOwner ? fullNameOrEmail(transferOwner) : 'Choose a new owner'}
                    </LemonButton>
                )}
            </MemberSelect>
            <p className="mt-3 mb-0 text-secondary">
                The new owner must have access to each project and the data it uses. Recipients stay the same.
            </p>
        </LemonModal>
    )
}
