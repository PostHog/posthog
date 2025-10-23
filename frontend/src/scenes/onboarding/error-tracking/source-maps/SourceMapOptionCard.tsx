import { LemonCard } from '@posthog/lemon-ui'

export interface SourceMapOptionCardProps {
    title: string
    description: string
    optionKey: string
    selectedOption: string | null
    onSelect: () => void
    children?: React.ReactNode
}

export function SourceMapOptionCard({
    title,
    description,
    optionKey,
    selectedOption,
    onSelect,
    children,
}: SourceMapOptionCardProps): JSX.Element {
    const isSelected = selectedOption === optionKey

    return (
        <LemonCard
            className={`p-4 cursor-pointer border-2 ${isSelected ? 'border-[var(--primary-3000-frame-bg-light)]' : 'border-transparent'}`}
            onClick={onSelect}
        >
            <h4 className="font-semibold mb-2">{title}</h4>
            <p className={`text-sm text-muted ${children ? 'mb-2' : 'mb-0'}`}>{description}</p>
            {isSelected && children}
        </LemonCard>
    )
}
