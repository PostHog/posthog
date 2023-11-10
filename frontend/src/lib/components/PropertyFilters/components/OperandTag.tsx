import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

export const OperandTag = ({ operand }: { operand: 'and' | 'or' }): JSX.Element => {
    const tag: { type: LemonTagType; label: string } =
        operand === 'and' ? { type: 'highlight', label: 'AND' } : { type: 'completion', label: 'OR' }

    return (
        <div className="flex w-full justify-center">
            <LemonTag type={tag.type}>{tag.label}</LemonTag>
        </div>
    )
}
