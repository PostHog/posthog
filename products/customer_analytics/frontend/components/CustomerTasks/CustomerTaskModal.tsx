import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonModal,
    LemonTextArea,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { dayjsLocalToTimezone, dayjsUtcToTimezone } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { fullName } from 'lib/utils/strings'

import { customerTaskEditDisabledReason, type CustomerTasksContext } from './customerTaskFilters'
import type { customerTasksLogicType } from './customerTasksLogic'

export interface CustomerTaskModalProps {
    logic: import('kea').BuiltLogic<customerTasksLogicType>
    context: CustomerTasksContext
}

export function CustomerTaskModal({ logic, context }: CustomerTaskModalProps): JSX.Element {
    const {
        modalOpen,
        modalTask,
        accountOptions,
        accountOptionsResponseLoading,
        draftName,
        draftDescription,
        draftAccount,
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
        setDraftAccount,
        setDraftAssignedTo,
        setDraftDueAt,
        submitModal,
    } = useActions(logic)
    const saving = Boolean(mutationKeys[modalTask?.id ?? 'create'])
    const create = modalTask === null
    const editDisabledReason = modalTask ? customerTaskEditDisabledReason(modalTask) : undefined
    const editable = !editDisabledReason
    const disabledReason = editDisabledReason ?? (saving ? 'Saving' : undefined)
    const accountOptionsForSelect = accountOptions.map((account) => ({ key: account.id, label: account.name }))
    if (draftAccount && !accountOptionsForSelect.some((option) => option.key === draftAccount.id)) {
        accountOptionsForSelect.unshift({ key: draftAccount.id, label: draftAccount.name })
    }
    const close = (): void => {
        if (!saving) {
            closeModal()
        }
    }

    return (
        <LemonModal
            isOpen={modalOpen}
            onClose={close}
            closable={!saving}
            title={create ? 'New task' : editable ? 'Edit task' : 'Task details'}
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={close} disabledReason={saving ? 'Saving' : undefined}>
                        {editable ? 'Cancel' : 'Close'}
                    </LemonButton>
                    {editable && (
                        <LemonButton
                            type="primary"
                            onClick={submitModal}
                            loading={saving}
                            disabledReason={!draftName.trim() ? 'Enter a task name' : undefined}
                        >
                            {create ? 'Create task' : 'Save changes'}
                        </LemonButton>
                    )}
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <LemonLabel>Task name</LemonLabel>
                    <LemonInput
                        value={draftName}
                        onChange={setDraftName}
                        maxLength={400}
                        autoFocus={editable}
                        fullWidth
                        disabledReason={disabledReason}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Description (optional)</LemonLabel>
                    <LemonTextArea
                        value={draftDescription}
                        onChange={setDraftDescription}
                        minRows={4}
                        disabled={Boolean(disabledReason)}
                    />
                </div>
                {context === 'inbox' && (
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Account (optional)</LemonLabel>
                        <div className="flex flex-wrap items-center gap-2">
                            <div className="min-w-64 flex-1">
                                <LemonInputSelect
                                    mode="single"
                                    value={draftAccount ? [draftAccount.id] : []}
                                    options={accountOptionsForSelect}
                                    loading={accountOptionsResponseLoading}
                                    onInputChange={(query) => loadAccountOptions({ query })}
                                    onChange={(values) => {
                                        const accountId = values[0]
                                        if (!accountId) {
                                            setDraftAccount(null)
                                            return
                                        }
                                        const account = accountOptions.find((option) => option.id === accountId)
                                        setDraftAccount(
                                            account ? { id: account.id, name: account.name } : (draftAccount ?? null)
                                        )
                                    }}
                                    placeholder="No account"
                                    disabledReason={disabledReason}
                                    fullWidth
                                    data-attr="customer-task-account"
                                />
                            </div>
                            {draftAccount && (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconX />}
                                    onClick={() => setDraftAccount(null)}
                                    disabledReason={disabledReason}
                                >
                                    Remove account
                                </LemonButton>
                            )}
                        </div>
                    </div>
                )}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Assignee (optional)</LemonLabel>
                    <MemberSelect
                        value={draftAssignedTo?.id ?? null}
                        defaultLabel="Unassigned"
                        type="secondary"
                        size="small"
                        onChange={(user) =>
                            setDraftAssignedTo(
                                user
                                    ? {
                                          id: user.id,
                                          email: user.email,
                                          first_name: user.first_name,
                                          last_name: user.last_name ?? '',
                                      }
                                    : null
                            )
                        }
                    >
                        {(selected) => {
                            const assignee = selected ?? draftAssignedTo
                            return (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    disabledReason={disabledReason}
                                    icon={
                                        assignee ? (
                                            <ProfilePicture user={{ email: assignee.email }} size="sm" />
                                        ) : undefined
                                    }
                                >
                                    {assignee ? fullName(assignee) || assignee.email : 'Unassigned'}
                                </LemonButton>
                            )
                        }}
                    </MemberSelect>
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Due date (optional)</LemonLabel>
                    <LemonCalendarSelectInput
                        value={draftDueAt ? dayjsUtcToTimezone(draftDueAt, timezone) : null}
                        onChange={(value) =>
                            setDraftDueAt(
                                value
                                    ? dayjsLocalToTimezone(value.format('YYYY-MM-DDTHH:mm'), timezone).toISOString()
                                    : null
                            )
                        }
                        granularity="minute"
                        format="MMM D, YYYY HH:mm"
                        use24HourFormat
                        placeholder="No due date"
                        buttonProps={{
                            disabledReason,
                            sideAction: draftDueAt
                                ? {
                                      icon: <IconX />,
                                      onClick: () => setDraftDueAt(null),
                                      disabledReason,
                                      'aria-label': 'Clear date',
                                  }
                                : undefined,
                        }}
                    />
                </div>
            </div>
        </LemonModal>
    )
}
