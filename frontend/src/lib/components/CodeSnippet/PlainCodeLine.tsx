import clsx from 'clsx'
import { useValues } from 'kea'

import { themeLogic } from 'lib/logic/themeLogic'

export function PlainCodeLine({ text, className }: { text: string; className?: string }): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    return <code className={clsx('hljs', isDarkModeOn && 'hljs-dark', className)}>{text}</code>
}
