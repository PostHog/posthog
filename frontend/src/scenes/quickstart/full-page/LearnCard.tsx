import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { captureQuickstartAction } from '../shared/captureQuickstartAction'

interface LearnQuickLink {
    label: string
    to?: string
    targetBlank?: boolean
    onClick?: () => void
}

export function LearnCard({
    icon,
    title,
    description,
    buttonLabel,
    to,
    targetBlank,
    onClick,
    action,
    quickLinks,
}: {
    icon: JSX.Element
    title: string
    description: string
    buttonLabel: string
    to?: string
    targetBlank?: boolean
    onClick?: () => void
    action: string
    quickLinks?: LearnQuickLink[]
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4 rounded-lg border-transparent shadow-sm">
            <span className="text-xl text-secondary">{icon}</span>
            <h3 className="font-semibold text-base mb-0">{title}</h3>
            <p className="text-secondary text-sm mb-0">{description}</p>
            {quickLinks ? (
                <>
                    <ul className="flex flex-col gap-1.5 my-1 flex-1">
                        {quickLinks.map((link) => (
                            <li key={link.label}>
                                <Link
                                    to={link.to}
                                    target={link.targetBlank ? '_blank' : undefined}
                                    targetBlankIcon={false}
                                    onClick={() => {
                                        captureQuickstartAction(`${action}_quick_link`, undefined, {
                                            link_label: link.label,
                                        })
                                        link.onClick?.()
                                    }}
                                    subtle
                                    className="text-sm font-normal"
                                    data-attr={`quickstart-learn-${action}-quick-link`}
                                >
                                    {link.label}
                                </Link>
                            </li>
                        ))}
                    </ul>
                    <div className="mt-auto flex">
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={to}
                            targetBlank={targetBlank}
                            onClick={() => {
                                captureQuickstartAction(action)
                                onClick?.()
                            }}
                            data-attr={`quickstart-learn-${action}`}
                        >
                            {buttonLabel}
                        </LemonButton>
                    </div>
                </>
            ) : (
                <div className="mt-auto flex">
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={to}
                        targetBlank={targetBlank}
                        onClick={() => {
                            captureQuickstartAction(action)
                            onClick?.()
                        }}
                        data-attr={`quickstart-learn-${action}`}
                    >
                        {buttonLabel}
                    </LemonButton>
                </div>
            )}
        </LemonCard>
    )
}
