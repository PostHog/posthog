import { LemonTag } from '@posthog/lemon-ui'

export function CategoryTag({ category }: { category: string }): JSX.Element {
    const colors: Record<string, 'primary' | 'highlight' | 'caution'> = {
        commercial: 'primary',
        informational: 'highlight',
        navigational: 'caution',
    }
    return <LemonTag type={colors[category] || 'default'}>{category}</LemonTag>
}
