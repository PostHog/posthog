import { HogCallable, HogClosure, HogDate, HogDateTime, HogError, HogUpValue } from './types'

export function isHogDate(obj: any): obj is HogDate {
    return obj && typeof obj === 'object' && '__hogDate__' in obj && 'year' in obj && 'month' in obj && 'day' in obj
}

export function isHogDateTime(obj: any): obj is HogDateTime {
    return obj && typeof obj === 'object' && '__hogDateTime__' in obj && 'dt' in obj && 'zone' in obj
}

export function isHogError(obj: any): obj is HogError {
    return obj && typeof obj === 'object' && '__hogError__' in obj && 'type' in obj && 'message' in obj
}

export function newHogError(type: string, message: string, payload?: Record<string, any>): HogError {
    return {
        __hogError__: true,
        type: type || 'Error',
        message: message || 'An error occurred',
        payload,
    }
}

export function isHogCallable(obj: any): obj is HogCallable {
    return (
        obj &&
        typeof obj === 'object' &&
        '__hogCallable__' in obj &&
        'argCount' in obj &&
        'ip' in obj &&
        // 'chunk' in obj &&  // TODO: enable after this has been live for some hours
        'upvalueCount' in obj
    )
}

export function isHogClosure(obj: any): obj is HogClosure {
    return obj && typeof obj === 'object' && '__hogClosure__' in obj && 'callable' in obj && 'upvalues' in obj
}

export function newHogClosure(callable: HogCallable, upvalues?: number[]): HogClosure {
    return {
        __hogClosure__: true,
        callable,
        upvalues: upvalues ?? [],
    }
}

export function newHogCallable(
    type: HogCallable['__hogCallable__'],
    {
        name,
        chunk,
        argCount,
        upvalueCount,
        ip,
    }: {
        name: string
        chunk: string
        argCount: number
        upvalueCount: number
        ip: number
    }
): HogCallable {
    return {
        __hogCallable__: type,
        name,
        chunk: chunk,
        argCount,
        upvalueCount,
        ip,
    } satisfies HogCallable
}

export function isHogUpValue(obj: any): obj is HogUpValue {
    return (
        obj &&
        typeof obj === 'object' &&
        '__hogUpValue__' in obj &&
        'location' in obj &&
        'closed' in obj &&
        'value' in obj
    )
}

export function isHogAST(obj: any): boolean {
    return obj && ((typeof obj === 'object' && '__hx_ast' in obj) || (obj instanceof Map && obj.get('__hx_ast')))
}
