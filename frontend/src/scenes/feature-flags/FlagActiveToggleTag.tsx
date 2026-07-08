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

    const handleToggle = (): void => {
        if (!toggling) {
            onToggle(!active)
        }
    }

    return (
        <LemonTag
            type={active ? 'success' : 'default'}
            className="uppercase gap-1"
            onClick={handleToggle}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    handleToggle()
                }
            }}
            tabIndex={0}
            role="switch"
            aria-checked={active}
            aria-label="Feature flag active in this project"
            disabledReason={toggling ? 'Updating…' : undefined}
            data-attr={dataAttr}
        >
            <span aria-hidden className="pointer-events-none flex items-center">
                <LemonSwitch checked={active} size="xxsmall" loading={toggling} sliderColorOverrideChecked="success" />
            </span>
            {label}
        </LemonTag>
    )
}
