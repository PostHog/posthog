import { type BuiltLogic, type LogicWrapper, useMountedLogic } from 'kea'

export function WelcomeProductDetection({ statusLogic }: { statusLogic: BuiltLogic | LogicWrapper }): null {
    useMountedLogic(statusLogic)
    return null
}
