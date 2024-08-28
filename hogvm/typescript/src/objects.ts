export interface CallFrame {
    closure: HogClosure
    ip: number
    stackStart: number
    argCount: number
}

export interface ThrowFrame {
    callStackLen: number
    stackLen: number
    catchIp: number
}

export interface HogDate {
    __hogDate__: true
    year: number
    month: number
    day: number
}

export interface HogDateTime {
    __hogDateTime__: true
    /** Timestamp float in seconds */
    dt: number
    zone: string
}

export interface HogError {
    __hogError__: true
    type: string
    message: string
    payload?: Record<string, any>
}

export interface HogCallable {
    __hogCallable__: 'local' | 'stl' | 'async' | 'main'
    name?: string
    argCount: number
    upvalueCount: number
    ip: number
}

export interface HogUpValue {
    __hogUpValue__: true
    id: number
    location: number
    closed: boolean
    value: any
}

export interface HogClosure {
    __hogClosure__: true
    callable: HogCallable
    upvalues: number[]
}

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
        argCount,
        upvalueCount,
        ip,
    }: {
        name: string
        argCount: number
        upvalueCount: number
        ip: number
    }
): HogCallable {
    return {
        __hogCallable__: type,
        name,
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
