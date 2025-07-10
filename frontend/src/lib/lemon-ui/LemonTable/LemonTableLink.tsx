import { LemonMarkdown } from '../LemonMarkdown'
import { Link, LinkProps } from '../Link'

export function LemonTableLink({
    title,
    description,
    ...props
}: Pick<LinkProps, 'to' | 'onClick' | 'target' | 'className'> & {
    title: JSX.Element | string
    description?: JSX.Element | string
}): JSX.Element {
    return (
        <Link subtle {...props}>
            <div className="flex flex-col py-1">
                <div className="flex flex-row items-center gap-1 text-sm font-semibold">{title}</div>

                {description ? (
                    <div className="text-tertiary mt-1 text-xs">
                        {typeof description === 'string' ? (
                            <LemonMarkdown className="max-w-[30rem]" lowKeyHeadings>
                                {description}
                            </LemonMarkdown>
                        ) : (
                            description
                        )}
                    </div>
                ) : null}
            </div>
        </Link>
    )
}
