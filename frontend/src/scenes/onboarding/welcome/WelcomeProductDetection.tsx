import { type LogicWrapper, useMountedLogic } from 'kea'

export function WelcomeProductDetection({
    statusLogic,
    children,
}: {
    statusLogic: LogicWrapper
    children: JSX.Element
}): JSX.Element {
    useMountedLogic(statusLogic)
    return children
}
