import { ReactNode } from 'react'

import { LemonMarkdown } from '../LemonMarkdown'
import { Link, LinkProps } from '../Link'
import { IconOpenInNew } from '../icons'

interface LemonTableLinkContentProps {
    title: JSX.Element | string
    description?: ReactNode
    target?: string
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
        <Link subtle {...props} targetBlankIcon={false}>
            <LemonTableLinkContent title={title} description={description} target={props.target} />
        </Link>
    )
}

function LemonTableLinkContent({ title, description, target }: LemonTableLinkContentProps): JSX.Element {
    return (
        <div className="flex flex-col py-1">
            <div className="flex flex-row items-center font-semibold text-sm gap-1">
                <span>{title}</span>
                {target === '_blank' && <IconOpenInNew />}
            </div>

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
