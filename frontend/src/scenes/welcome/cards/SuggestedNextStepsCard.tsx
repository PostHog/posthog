import { useActions, useValues } from 'kea'

import { IconArrowRight, IconBook } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { FALLBACK_BRANDING, PRODUCT_BRANDING } from '../productBranding'
import { welcomeDialogLogic } from '../welcomeDialogLogic'

export function SuggestedNextStepsCard(): JSX.Element | null {
    const { suggestedNextSteps } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (suggestedNextSteps.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-4">
            <h2 className="text-lg font-semibold mb-3">Suggested next steps</h2>
            <ul className="flex flex-col gap-3 m-0 p-0 list-none">
                {suggestedNextSteps.map((step, index) => {
                    const branding = (step.product_key && PRODUCT_BRANDING[step.product_key]) || FALLBACK_BRANDING
                    const Icon = branding.Icon
                    return (
                        <li key={`${step.href}-${index}`} className="flex items-start gap-3">
                            <div
                                className="flex-shrink-0 w-8 h-8 rounded-md flex items-center justify-center"
                                /* eslint-disable-next-line react/forbid-dom-props */
                                style={{
                                    backgroundColor: `rgb(${branding.rgb} / 0.12)`,
                                    color: `rgb(${branding.rgb})`,
                                }}
                                aria-hidden="true"
                            >
                                <Icon className="text-lg" />
                            </div>
                            <div className="flex-1 min-w-0">
                                <Link
                                    to={step.href}
                                    subtle
                                    onClick={() => trackCardClick('next_steps', step.href)}
                                    className="inline-flex items-center gap-1 font-medium"
                                >
                                    <span>{step.label}</span>
                                    <IconArrowRight className="text-sm" />
                                </Link>
                                <div className="text-xs text-muted">{step.reason}</div>
                            </div>
                            {step.docs_href ? (
                                <Link
                                    to={step.docs_href}
                                    target="_blank"
                                    subtle
                                    onClick={() => trackCardClick('next_steps', step.docs_href!)}
                                    className="inline-flex items-center gap-1 text-xs text-muted flex-shrink-0 mt-0.5"
                                >
                                    <IconBook />
                                    <span>Docs</span>
                                </Link>
                            ) : null}
                        </li>
                    )
                })}
            </ul>
        </LemonCard>
    )
}
