import { type LogicWrapper, useMountedLogic } from 'kea'

export function WelcomeProductDetection({ statusLogic }: { statusLogic: LogicWrapper }): null {
    useMountedLogic(statusLogic)
    return null
}
