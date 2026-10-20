import { IconExternal, IconGear } from '@posthog/icons'
import { cn } from '@posthog/quill'

import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'
import { QuillLabeledSwitch } from 'lib/components/QuillLabeledSwitch/QuillLabeledSwitch'

export interface QuillTestAccountFilterSwitchProps {
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: React.ReactNode
    /** Configures the filters in place; without it the gear opens settings in a new tab. */
    onConfigure?: () => void
    showNewTabIcon: boolean
    /** The router link the gear renders as when it opens settings in a new tab. */
    settingsLink: React.ReactElement
    id?: string
    className?: string
    'data-attr'?: string
}

export function QuillTestAccountFilterSwitch({
    checked,
    onChange,
    disabledReason,
    onConfigure,
    showNewTabIcon,
    settingsLink,
    id = 'test-account-filter',
    className,
    'data-attr': dataAttr,
}: QuillTestAccountFilterSwitchProps): JSX.Element {
    return (
        <div className={cn('flex items-center gap-1', className)}>
            <QuillLabeledSwitch
                id={id}
                checked={checked}
                onChange={onChange}
                disabledReason={disabledReason}
                label="Filter out internal and test users"
                data-attr={dataAttr}
            />
            {onConfigure ? (
                <QuillIconButton
                    size="icon-sm"
                    label="Configure internal and test users"
                    icon={<IconGear />}
                    onClick={onConfigure}
                />
            ) : (
                <QuillIconButton
                    size="icon-sm"
                    label="Configure internal and test users. Opens in a new tab."
                    icon={showNewTabIcon ? <IconExternal /> : <IconGear />}
                    render={settingsLink}
                    nativeButton={false}
                />
            )}
        </div>
    )
}
