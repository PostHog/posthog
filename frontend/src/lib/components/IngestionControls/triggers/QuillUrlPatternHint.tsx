import { Item, ItemContent, ItemDescription } from '@posthog/quill'

const CODE_CLASS = 'rounded-sm bg-muted px-1 font-mono'

export function QuillUrlPatternHint(): JSX.Element {
    return (
        <Item tone="info" size="sm">
            <ItemContent>
                <ItemDescription>
                    Patterns are wrapped in{' '}
                    <code data-quill className={CODE_CLASS}>
                        ^
                    </code>{' '}
                    and{' '}
                    <code data-quill className={CODE_CLASS}>
                        $
                    </code>{' '}
                    and matched against the full URL, so a path on its own never matches. Write the full URL, e.g.{' '}
                    <code data-quill className={CODE_CLASS}>
                        https://example.com/checkout.*
                    </code>
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
