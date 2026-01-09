import { ErrorTrackingException } from '../../types'

export class KnownExceptionRegistry {
    private static knownExceptionList: KnownException[] = []

    static register(exception: KnownException): void {
        this.knownExceptionList.push(exception)
    }

    static match(exception: ErrorTrackingException): KnownException | undefined {
        try {
            return this.knownExceptionList.find((knownException) => knownException.match(exception))
        } catch {
            return undefined
        }
    }
}

export const knownExceptionRegistry = KnownExceptionRegistry

export interface KnownException {
    match: (exception: ErrorTrackingException) => boolean
    render: (exception: ErrorTrackingException) => JSX.Element
}

export function defineKnownException<T extends KnownException>(exception: T): T {
    KnownExceptionRegistry.register(exception)
    return exception
}
