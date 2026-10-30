import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { TodayFilterMenuTrigger } from '~/layout/today/TodayFilterMenuTrigger'
import { TodayRecentRadioSubmenu } from '~/layout/today/TodayRecentRadioSubmenu'
import { membersLogic } from '~/models/membersLogic'

const ANY_USER = 'any'

/** The notebook picker's filters, laid out like the rail's: one row per filter, and a way to clear them. */
export function QuillNotebookFilterMenu({
    createdBy,
    setCreatedBy,
}: {
    /** The creator's user uuid, or null for anyone. */
    createdBy: string | null
    setCreatedBy: (userUuid: string | null) => void
}): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    const { user } = useValues(userLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    const createdByOptions = useMemo(
        () => [
            { value: ANY_USER, label: 'Any user' },
            ...meFirstMembers.map(({ user: member }) => ({
                value: member.uuid,
                label: member.uuid === user?.uuid ? 'Me' : fullName(member),
            })),
        ],
        [meFirstMembers, user]
    )

    return (
        <DropdownMenu onOpenChange={(open) => open && ensureAllMembersLoaded()}>
            <TodayFilterMenuTrigger active={createdBy !== null} dataAttr="notebooks-select-button-filter" />
            <DropdownMenuContent align="end" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Created by"
                    options={createdByOptions}
                    value={createdBy ?? ANY_USER}
                    defaultValue={ANY_USER}
                    onChange={(value) => setCreatedBy(value === ANY_USER ? null : value)}
                    dataAttr="notebooks-select-button-created-by"
                />
                {createdBy !== null && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() => setCreatedBy(null)}
                            data-attr="notebooks-select-button-filter-clear"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
