import { LemonTag } from '@posthog/lemon-ui'

export const OperandTag = ({ operand, className }: { operand: 'and' | 'or'; className?: string }): JSX.Element => {
    return (
        <LemonTag type={operand === 'and' ? 'highlight' : 'completion'} className={className}>
            <span className="uppercase">{operand}</span>
        </LemonTag>
    )
}
