import { IconFilter } from '@posthog/icons'
import { Badge, Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { IconSubArrowRight } from 'lib/lemon-ui/icons'

import { ConditionRowProps, OPERATOR_DISPLAY } from './triggerGroupHelpers'

const LABELS: Record<ConditionRowProps['type'], string> = {
    events: 'Event',
    urls: 'User has visited URL matching pattern',
    flag: 'Feature flag',
}

const ACTIONS: Record<ConditionRowProps['type'], string> = {
    events: 'occurred',
    urls: '',
    flag: 'is enabled',
}

export function QuillTriggerGroupConditionRow({
    type,
    values,
    matchType,
    isFirst,
    eventConfigs,
}: ConditionRowProps & { isFirst: boolean }): JSX.Element {
    const showArrow = matchType === 'any' || isFirst

    return (
        <div className="flex flex-wrap items-center gap-1.5">
            {showArrow ? (
                <IconSubArrowRight className="shrink-0 text-muted-foreground" />
            ) : (
                <Text size="xs" weight="medium" variant="muted" render={<span />}>
                    &
                </Text>
            )}
            <Text size="xs" variant="muted" render={<span />}>
                {LABELS[type]}
            </Text>
            {values.map((value, idx) => {
                const config = eventConfigs?.find((e) => e.name === value)
                const filters = config?.properties ?? []

                return (
                    <span key={value} className="contents">
                        {idx > 0 && (
                            <Text size="xs" variant="muted" render={<span />}>
                                or
                            </Text>
                        )}
                        <Badge>{value}</Badge>
                        {filters.length > 0 && (
                            <Tooltip>
                                <TooltipTrigger
                                    delay={0}
                                    render={
                                        <Button
                                            size="xs"
                                            aria-label={`${filters.length} property filters on ${value}`}
                                        />
                                    }
                                >
                                    <IconFilter />
                                    <span>{filters.length}</span>
                                </TooltipTrigger>
                                <TooltipContent>
                                    <div className="flex flex-col gap-1">
                                        <span className="font-semibold">Where:</span>
                                        {filters.map((f, i) => (
                                            <span key={i} className="flex items-baseline gap-1.5">
                                                <span className="font-medium">{f.key}</span>
                                                <span>{OPERATOR_DISPLAY[f.operator || 'exact'] || f.operator}</span>
                                                <span className="font-medium">
                                                    {Array.isArray(f.value)
                                                        ? f.value.join(', ')
                                                        : String(f.value ?? '')}
                                                </span>
                                            </span>
                                        ))}
                                    </div>
                                </TooltipContent>
                            </Tooltip>
                        )}
                    </span>
                )
            })}
            {ACTIONS[type] && (
                <Text size="xs" variant="muted" render={<span />}>
                    {ACTIONS[type]}
                </Text>
            )}
        </div>
    )
}
