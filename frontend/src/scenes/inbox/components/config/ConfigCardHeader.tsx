import { ReactNode } from 'react'

/** Icon + title + description header shared by the agent-setup config cards. Pass the icon pre-sized (size-5). */
export function ConfigCardHeader({
    icon,
    title,
    description,
}: {
    icon: ReactNode
    title: string
    description: ReactNode
}): JSX.Element {
    return (
        <div className="flex items-start gap-3 min-w-0">
            {icon}
            <div className="min-w-0">
                <div className="font-medium text-sm text-default">{title}</div>
                <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">{description}</p>
            </div>
        </div>
    )
}
