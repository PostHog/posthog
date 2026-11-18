import { useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { SSOProvider } from '~/types'

import { SSOSelectInterface } from './SSOSelect'
import { ssoSelectOptions } from './ssoSelectOptions'

export function QuillSSOSelect({
    value,
    loading,
    onChange,
    samlAvailable,
    oidcAvailable,
    disabledReason,
}: SSOSelectInterface): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight) {
        return null
    }

    const options = ssoSelectOptions(preflight, samlAvailable, oidcAvailable)
    const items = options.map((option) => ({ value: option.value, label: option.label }))
    const reason = loading ? 'Cannot change while loading' : disabledReason

    return (
        <Select<SSOProvider | ''>
            items={items}
            value={value}
            onValueChange={(next) => onChange((next ?? '') as SSOProvider | '')}
        >
            <SelectTrigger className="w-full min-w-40" disabledReason={reason}>
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value} disabledReason={option.disabledReason}>
                        {option.icon}
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
