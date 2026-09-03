import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonInputSelect, LemonLabel, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { dayjsLocalToTimezone, dayjsUtcToTimezone } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import { customerTaskEditDisabledReason } from './customerTaskFilters'
import type { customerTasksLogicType } from './customerTasksLogic'
export interface CustomerTaskModalProps {
    logic: import('kea').BuiltLogic<customerTasksLogicType>
    accountName?: string
}
export function CustomerTaskModal({ logic, accountName }: CustomerTaskModalProps): JSX.Element {
    const {
        modalOpen,
        modalTask,
        accountOptions,
        accountOptionsResponseLoading,
        draftName,
        draftDescription,
        draftAccountId,
        draftAssignedTo,
        draftDueAt,
        mutationKeys,
        timezone,
    } = useValues(logic)
    const {
        closeModal,
        loadAccountOptions,
        setDraftName,
        setDraftDescription,
        setDraftAccountId,
        setDraftAssignedTo,
        setDraftDueAt,
        submitModal,
    } = useActions(logic)
    const saving = Boolean(mutationKeys[modalTask?.id ?? 'create'])
    const create = modalTask === null
    const editDisabledReason = modalTask ? customerTaskEditDisabledReason(modalTask) : undefined
    const accountOptionsForSelect = accountOptions.map((account) => ({ key: account.id, label: account.name }))
    if (draftAccountId && !accountOptionsForSelect.some((option) => option.key === draftAccountId)) {
        const selectedAccountName = modalTask?.account?.id === draftAccountId ? modalTask.account.name : accountName
        if (selectedAccountName) {
            accountOptionsForSelect.unshift({ key: draftAccountId, label: selectedAccountName })
        }
    }
    return (
        <LemonModal
            isOpen={modalOpen}
            onClose={closeModal}
            title={create ? 'New task' : 'Edit task'}
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal} disabledReason={saving ? 'Saving' : undefined}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitModal}
                        loading={saving}
                        disabledReason={editDisabledReason ?? (!draftName.trim() ? 'Enter a task name' : undefined)}
                    >
                        {create ? 'Create task' : 'Save changes'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <LemonLabel>Task name</LemonLabel>
                    <LemonInput value={draftName} onChange={setDraftName} maxLength={400} autoFocus fullWidth />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Description (optional)</LemonLabel>
                    <LemonTextArea value={draftDescription} onChange={setDraftDescription} minRows={4} />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Account (optional)</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        value={draftAccountId ? [draftAccountId] : []}
                        options={accountOptionsForSelect}
                        loading={accountOptionsResponseLoading}
                        onInputChange={(query) => loadAccountOptions({ query })}
                        onChange={(values) => setDraftAccountId(values[0] ?? null)}
                        placeholder="No account"
                        disabledReason={editDisabledReason}
                        fullWidth
                        data-attr="customer-task-account"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Assignee (optional)</LemonLabel>
                    <MemberSelect
                        value={draftAssignedTo}
                        defaultLabel="Unassigned"
                        type="secondary"
                        size="small"
                        onChange={(u) => setDraftAssignedTo(u?.id ?? null)}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Due date (optional)</LemonLabel>
                    <LemonCalendarSelectInput
                        value={draftDueAt ? dayjsUtcToTimezone(draftDueAt, timezone) : null}
                        onChange={(v) =>
                            setDraftDueAt(
                                v ? dayjsLocalToTimezone(v.format('YYYY-MM-DDTHH:mm'), timezone).toISOString() : null
                            )
                        }
                        granularity="minute"
                        format="MMM D, YYYY HH:mm"
                        use24HourFormat
                        clearable
                        placeholder="No due date"
                    />
                </div>
            </div>
        </LemonModal>
    )
}
