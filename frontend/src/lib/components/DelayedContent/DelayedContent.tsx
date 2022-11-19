import { useEffect, useState } from 'react'

interface DelayedContentProps {
    atStart: JSX.Element | string
    afterDelay: JSX.Element | string
}

export function DelayedContent({ atStart, afterDelay }: DelayedContentProps): JSX.Element {
    const [content, setContent] = useState<JSX.Element | string>(atStart)
    useEffect(() => {
        setTimeout(() => {
            setContent(afterDelay)
        }, 30000)
    }, [])
    return <>{content}</>
}
