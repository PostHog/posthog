import { actionScopeToName } from './constants'

export const getNameFromActionScope = (scope: string): string => {
    if (scope in actionScopeToName) {
        return actionScopeToName[scope]
    }
    return scope
}
