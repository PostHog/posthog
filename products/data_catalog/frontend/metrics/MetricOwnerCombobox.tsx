import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
} from '@posthog/quill'

import { fullNameOrEmail } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

const UNASSIGNED = 'unassigned'

interface MetricOwnerComboboxProps {
    label: string
    variant: 'default' | 'outline'
    onChange: (owner: string | null) => void
    dataAttr: string
    loading?: boolean
    disabledReason?: string
}

export function MetricOwnerCombobox({
    label,
    variant,
    onChange,
    dataAttr,
    loading,
    disabledReason,
}: MetricOwnerComboboxProps): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const optionLabels = new Map<string, string>([
        [UNASSIGNED, 'Unassigned'],
        ...meFirstMembers.map((member): [string, string] => [member.user.email, fullNameOrEmail(member.user)]),
    ])

    return (
        <Combobox
            items={[...optionLabels.keys()]}
            value={null}
            onOpenChange={(open: boolean) => open && ensureAllMembersLoaded()}
            onValueChange={(value: string | null) => value && onChange(value === UNASSIGNED ? null : value)}
            itemToStringLabel={(value: string) => optionLabels.get(value) ?? value}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={
                    <Button
                        variant={variant}
                        size="sm"
                        className="max-w-48 justify-start"
                        loading={loading}
                        disabledReason={disabledReason}
                        data-attr={dataAttr}
                    />
                }
            >
                <span className="truncate">{label}</span>
            </ComboboxTrigger>
            <ComboboxContent anchor={triggerRef} align="start" className="w-72">
                <ComboboxInput placeholder="Search members" aria-label="Search members" showTrigger={false} />
                <ComboboxEmpty>No members match that search.</ComboboxEmpty>
                <ComboboxList>
                    {(value: string) => (
                        <ComboboxItem key={value} value={value}>
                            <span className="truncate">{optionLabels.get(value)}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
