import { IconInfo } from '@posthog/icons'
import { LemonSwitch, Tooltip } from '@posthog/lemon-ui'

export function BotTrafficFilterSwitch({
    checked,
    onChange,
    ...switchProps
}: {
    checked: boolean
    onChange: (checked: boolean) => void
    bordered?: boolean
    fullWidth?: boolean
    labelClassName?: string
    className?: string
}): JSX.Element {
    return (
        <LemonSwitch
            checked={checked}
            onChange={onChange}
            label={
                <div className="flex items-center gap-1">
                    <span>Exclude bot traffic</span>
                    <Tooltip title="Drop exposures with a bot or empty user agent. This keeps server-side and crawler traffic out of your variant split.">
                        <IconInfo className="text-secondary" />
                    </Tooltip>
                </div>
            }
            {...switchProps}
        />
    )
}
