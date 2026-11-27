import { Card, Text } from '@posthog/quill'

export function QuillWizardCard({
    icon,
    name,
    description,
    badge,
    onClick,
    'data-attr': dataAttr,
}: {
    icon?: React.ReactNode
    name: string
    description: string
    badge?: string
    onClick: () => void
    'data-attr'?: string
}): JSX.Element {
    return (
        <Card size="sm" className="p-0">
            <button
                type="button"
                onClick={onClick}
                data-attr={dataAttr}
                className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
                {icon ? <span className="shrink-0">{icon}</span> : null}
                <span className="flex min-w-0 flex-1 flex-col">
                    <Text size="sm" weight="semibold" className="m-0" render={<span />}>
                        {name}
                    </Text>
                    <Text size="xs" variant="muted" className="m-0" render={<span />}>
                        {description}
                    </Text>
                </span>
                {badge ? (
                    <Text size="xs" variant="muted" className="m-0 shrink-0" render={<span />}>
                        {badge}
                    </Text>
                ) : null}
            </button>
        </Card>
    )
}
