import { ReactNode } from 'react'

import { LemonMarkdown } from '../LemonMarkdown'
import { Link, LinkProps } from '../Link'

interface LemonTableLinkContentProps {
    title: JSX.Element | string
    description?: ReactNode
}

export function LemonTableLink({
    title,
    description,
    ...props
}: Pick<LinkProps, 'to' | 'onClick' | 'target' | 'className'> & LemonTableLinkContentProps): JSX.Element {
    if (!props.to) {
        return <LemonTableLinkContent title={title} description={description} />
    }

    return (
        <Link subtle {...props}>
            <LemonTableLinkContent title={title} description={description} />
        </Link>
    )
}

function LemonTableLinkContent({ title, description }: LemonTableLinkContentProps): JSX.Element {
    return (
        <div className="flex flex-col py-1">
            <div className="flex flex-row items-center font-semibold text-sm gap-1">{title}</div>

            {description ? (
                <div className="text-xs text-tertiary mt-1">
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
    )
}
