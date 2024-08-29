import type crypto from 'crypto'
import type RE2 from 're2'

export interface VMState {
    /** Bytecode running in the VM */
    bytecode: any[]
    /** Stack of the VM */
    stack: any[]
    /** Values hoisted from the stack */
    upvalues: HogUpValue[]
    /** Call stack of the VM */
    callStack: CallFrame[] // [number, number, number][]
    /** Throw stack of the VM */
    throwStack: ThrowFrame[]
    /** Declared functions of the VM (deprecated) */
    declaredFunctions: Record<string, [number, number]>
    /** How many sync ops have been performed */
    ops: number
    /** How many async steps have been taken */
    asyncSteps: number
    /** Combined duration of sync steps */
    syncDuration: number
    /** Max memory used */
    maxMemUsed: number
}

export interface ExecOptions {
    /** Global variables to be passed into the function */
    globals?: Record<string, any>
    functions?: Record<string, (...args: any[]) => any>
    asyncFunctions?: Record<string, (...args: any[]) => Promise<any>>
    /** Timeout in milliseconds */
    timeout?: number
    /** Max number of async function that can happen. When reached the function will throw */
    maxAsyncSteps?: number
    /** Memory limit in bytes. This is calculated based on the size of the VM stack. */
    memoryLimit?: number
    /** External libraries */
    external?: {
        /** Pass in the proper RE2 library */
        re2?: typeof RE2
        /** NodeJS crypto */
        crypto?: typeof crypto
    }
}

export interface ExecResult {
    result: any
    finished: boolean
    asyncFunctionName?: string
    asyncFunctionArgs?: any[]
    state?: VMState
}

export interface CallFrame {
    closure: HogClosure
    ip: number
    chunk: string
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
    chunk: string
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

export interface STLFunction {
    fn: (args: any[], name: string, options?: ExecOptions) => any
    minArgs?: number
    maxArgs?: number
}

export interface AsyncSTLFunction {
    fn: (args: any[], name: string, options?: ExecOptions) => Promise<any>
    minArgs?: number
    maxArgs?: number
}
