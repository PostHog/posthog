import { LemonSkeleton } from '@posthog/lemon-ui'

export interface LiveStatCardProps {
    label: string
    value: number | null
    isLoading?: boolean
}

export const LiveStatCard = ({ label, value, isLoading }: LiveStatCardProps): JSX.Element => {
    return (
        <div className="flex flex-col">
            <span className="text-muted text-xs uppercase font-medium">{label}</span>
            {isLoading ? (
                <LemonSkeleton className="w-16 h-8 mt-1" />
            ) : (
                <span className="text-2xl font-bold">{value !== null ? value.toLocaleString() : '-'}</span>
            )}
        </div>
    )
}

export const LiveStatDivider = (): JSX.Element => <div className="w-px h-10 bg-border hidden md:block" />
