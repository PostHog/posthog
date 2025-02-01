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
                <div className="flex flex-row items-center font-semibold text-sm gap-1">{title}</div>

                {description ? (
                    <div className="text-text-3000 text-xs text-tertiary mt-1">
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
