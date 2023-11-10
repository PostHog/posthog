import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

export const OperandTag = ({ operand }: { operand: 'and' | 'or' }): JSX.Element => {
    const tag: { type: LemonTagType; label: string } =
        operand === 'and' ? { type: 'highlight', label: 'AND' } : { type: 'completion', label: 'OR' }

    return <LemonTag type={tag.type}>{tag.label}</LemonTag>
}
