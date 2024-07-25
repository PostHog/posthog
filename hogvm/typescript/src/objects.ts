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
