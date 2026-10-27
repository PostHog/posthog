import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { betFormLogic } from '../logics/betFormLogic'
import { BetFormActions } from './BetFormActions'

export function BetThesisCard({ id }: { id: string }): JSX.Element {
    const { thesis } = useValues(betFormLogic({ id }))
    return (
        <aside aria-label="Your bet in one sentence" className="Bets__thesisCard flex flex-col gap-4">
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Your bet in one sentence
            </Text>
            <p className="Bets__thesisSentence m-0" aria-live="polite">
                {thesis.map((part, index) => (
                    <span
                        key={index}
                        className={`Bets__thesisPart Bets__thesisPart--${part.tone}${part.keep ? ' whitespace-nowrap' : ''}`}
                    >
                        {part.text}
                    </span>
                ))}
            </p>
            <Text size="xs" variant="muted" render={<p className="Bets__thesisNext m-0" />}>
                Bets checks the tracking first, then a Scout looks for ideas. Nothing is built until you choose an idea.
            </Text>
            <BetFormActions id={id} className="Bets__cardActions" />
        </aside>
    )
}
