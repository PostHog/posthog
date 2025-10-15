import { jest } from '@jest/globals'

export const exec = jest.fn()
export const execAsync = jest.fn(() => Promise.resolve({}))
export type ExecOptions = unknown
export type ExecResult = unknown
export type VMState = unknown
