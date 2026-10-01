import { LemonTag } from 'lib/lemon-ui/LemonTag'

/** The release stage label a sidebar product carries, such as alpha or beta. */
export function ProductTag({ tag, className }: { tag: string; className?: string }): JSX.Element {
    return (
        <LemonTag
            type={tag === 'alpha' ? 'completion' : tag === 'beta' ? 'warning' : 'success'}
            size="small"
            className={className}
        >
            {tag}
        </LemonTag>
    )
}
