import { LemonMarkdown } from '../LemonMarkdown'
import { Link, LinkProps } from '../Link'

// TODO: Rename as it might not always be a link
export function LemonTableLink({
    title,
    description,
    ...props
}: Pick<LinkProps, 'to' | 'onClick'> & {
    title: JSX.Element | string
    description?: string
}): JSX.Element {
    return (
        <Link subtle {...props}>
            <div className="flex flex-col py-1">
                <div className="flex flex-row items-center font-semibold text-sm">{title}</div>

                {description && (
                    <LemonMarkdown
                        className="text-default max-w-[30rem] text-xs text-text-secondary-3000"
                        lowKeyHeadings
                    >
                        {description}
                    </LemonMarkdown>
                )}
            </div>
        </Link>
    )
}
