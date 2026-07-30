import { LemonSwitch, LemonTag } from '@posthog/lemon-ui'

export function FlagActiveToggleTag({
    active,
    toggling,
    onToggle,
    'data-attr': dataAttr,
}: {
    active: boolean
    toggling?: boolean
    onToggle?: (active: boolean) => void
    'data-attr'?: string
}): JSX.Element {
    const label = active ? 'Enabled' : 'Disabled'
    if (!onToggle) {
        return (
            <LemonTag type={active ? 'success' : 'default'} className="uppercase" data-attr={dataAttr}>
                {label}
            </LemonTag>
        )
    }

    return (
        <LemonTag
            type={active ? 'success' : 'default'}
            className="uppercase"
            aria-busy={toggling || undefined}
            data-attr={dataAttr}
        >
            <LemonSwitch
                checked={active}
                onChange={() => onToggle(!active)}
                size="xxsmall"
                loading={toggling}
                disabledReason={toggling ? 'Updating…' : undefined}
                sliderColorOverrideChecked="success"
                aria-label="Feature flag active in this project"
                label={label}
                // LemonSwitch renders the label before the switch; reverse to keep the switch on the left
                className="flex-row-reverse"
            />
        </LemonTag>
    )
}
