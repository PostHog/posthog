import { LemonTag } from '@posthog/lemon-ui'

export interface ResultsTagProps {
    isSignificant: boolean
}

export function ResultsTag({ isSignificant }: ResultsTagProps): JSX.Element {
    return (
        <LemonTag type={isSignificant ? 'success' : 'primary'}>
            <b className="uppercase">{isSignificant ? 'Significant' : 'Not significant'}</b>
        </LemonTag>
    )
}
