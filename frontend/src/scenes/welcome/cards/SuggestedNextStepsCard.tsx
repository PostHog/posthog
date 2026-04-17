import { useActions, useValues } from 'kea'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

export function SuggestedNextStepsCard(): JSX.Element | null {
    const { suggestedNextSteps } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (suggestedNextSteps.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-6">
            <h2 className="text-lg font-semibold mb-3">Suggested next steps</h2>
            <ul className="flex flex-col gap-3">
                {suggestedNextSteps.map((step, index) => (
                    <li key={`${step.href}-${index}`}>
                        <Link to={step.href} onClick={() => trackCardClick('next_steps', step.href)}>
                            <span className="font-medium">{step.label}</span>
                        </Link>
                        <div className="text-xs text-muted">{step.reason}</div>
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}
