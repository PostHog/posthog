import { useActions, useValues } from 'kea'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'

interface TodaySessionHandoffDialogProps {
    sessionId: string
}

export function TodaySessionHandoffDialog({ sessionId }: TodaySessionHandoffDialogProps): JSX.Element {
    const { user } = useValues(userLogic)
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { handoffUser, pendingSessionIds } = useValues(todaySessionMenuLogic)
    const { closeHandoff, setHandoffUser, handOffSession } = useActions(todaySessionMenuLogic)
    const pending = pendingSessionIds.includes(sessionId)

    useOnMountEffect(ensureAllMembersLoaded)

    const candidates = meFirstMembers.filter((member) => member.user.id !== user?.id).map((member) => member.user)
    const names = new Map(candidates.map((candidate) => [candidate.id, fullName(candidate)]))

    return (
        <Dialog
            open
            onOpenChange={(open: boolean) => {
                if (!open && !pending) {
                    closeHandoff()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Hand off this session</DialogTitle>
                    <DialogDescription>
                        The person you choose takes over this session. They steer it and get its notifications. Only
                        they can hand it back.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <Field>
                        <FieldLabel htmlFor="today-session-handoff-user">Choose who takes over</FieldLabel>
                        <Combobox
                            items={candidates.map((candidate) => candidate.id)}
                            value={handoffUser?.id ?? null}
                            onValueChange={(userId: number | null) =>
                                setHandoffUser(candidates.find((candidate) => candidate.id === userId) ?? null)
                            }
                            itemToStringLabel={(userId: number) => names.get(userId) ?? ''}
                        >
                            <ComboboxInput
                                id="today-session-handoff-user"
                                placeholder="Choose a person"
                                data-attr="today-session-handoff-user"
                            />
                            <ComboboxContent>
                                <ComboboxEmpty>No one matches that name.</ComboboxEmpty>
                                <ComboboxList>
                                    {(userId: number) => (
                                        <ComboboxItem key={userId} value={userId}>
                                            {names.get(userId)}
                                        </ComboboxItem>
                                    )}
                                </ComboboxList>
                            </ComboboxContent>
                        </Combobox>
                    </Field>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeHandoff}
                        disabled={pending}
                        data-attr="today-session-handoff-cancel"
                    >
                        Cancel
                    </Button>
                    <Tooltip disabled={!!handoffUser}>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="primary"
                                    loading={pending}
                                    disabled={!handoffUser}
                                    onClick={() => handoffUser && handOffSession(sessionId, handoffUser)}
                                    data-attr="today-session-handoff-confirm"
                                />
                            }
                        >
                            Hand off
                        </TooltipTrigger>
                        <TooltipContent>Choose who takes over</TooltipContent>
                    </Tooltip>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
