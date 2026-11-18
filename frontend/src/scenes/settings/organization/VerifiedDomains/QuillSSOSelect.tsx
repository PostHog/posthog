import { useValues } from 'kea'

import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

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
    const trigger = (
        <SelectTrigger className="w-full min-w-40">
            <SelectValue />
        </SelectTrigger>
    )

    return (
        <Select<SSOProvider | ''>
            items={items}
            value={value}
            onValueChange={(next) => onChange((next ?? '') as SSOProvider | '')}
            disabled={!!reason}
        >
            {reason ? (
                <Tooltip>
                    <TooltipTrigger delay={0} render={trigger} />
                    <TooltipContent>{reason}</TooltipContent>
                </Tooltip>
            ) : (
                trigger
            )}
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value} disabled={!!option.disabledReason}>
                        {option.icon}
                        <span className="flex flex-col items-start gap-0.5">
                            {option.label}
                            {option.disabledReason && (
                                <Text size="xs" variant="muted" render={<span />}>
                                    {option.disabledReason}
                                </Text>
                            )}
                        </span>
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
