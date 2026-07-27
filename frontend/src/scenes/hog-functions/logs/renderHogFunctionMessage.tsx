import { Link } from '@posthog/lemon-ui'

const EVENT_LINK_REGEX = /Event: '(.+)'/g

export const renderHogFunctionMessage = (message: string): JSX.Element => {
    const parts = message.split(EVENT_LINK_REGEX)
    const elements: (string | JSX.Element)[] = []

    for (let i = 0; i < parts.length; i++) {
        if (i % 2 === 0) {
            // Even indices are regular text parts
            if (parts[i]) {
                elements.push(parts[i])
            }
        } else {
            elements.push(
                <Link className="rounded p-1 -m-1 bg-border text-bg-primary" to={parts[i]} targetBlankIcon>
                    View event
                </Link>
            )
        }
    }

    return <>{elements}</>
}
