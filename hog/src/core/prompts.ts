import * as clack from '@clack/prompts'
import { styleText } from 'node:util'

import { HogError } from './errors'

export interface Choice<Value extends string> {
    value: Value
    label: string
    hint?: string
}

export type Validate = (value: string) => string | undefined

export interface Spinner {
    stop(message: string): void
    error(message: string): void
}

export interface Prompts {
    // `help` is a dimmed line under the question that tells the person how to find the answer.
    select<Value extends string>(
        message: string,
        choices: readonly Choice<Value>[],
        options?: { help?: string }
    ): Promise<Value>
    text(message: string, options?: { initialValue?: string; validate?: Validate }): Promise<string>
    password(message: string, options?: { validate?: Validate }): Promise<string>
    confirm(message: string, options?: { initialValue?: boolean }): Promise<boolean>
    note(message: string, title: string): void
    spinner(message: string): Spinner
}

// Ctrl-C at a prompt. 130 is the exit code shells report for SIGINT.
const cancelled = (): HogError => new HogError('cancelled', 'Cancelled.', undefined, 130)

function answer<Value>(value: Value): Exclude<Value, symbol> {
    if (clack.isCancel(value)) {
        throw cancelled()
    }
    return value as Exclude<Value, symbol>
}

export function clackPrompts(): Prompts {
    return {
        async select<Value extends string>(
            message: string,
            choices: readonly Choice<Value>[],
            { help }: { help?: string } = {}
        ): Promise<Value> {
            const options = choices.map((choice) => ({ ...choice })) as Parameters<
                typeof clack.select<Value>
            >[0]['options']
            const question = help ? `${message}\n${styleText('dim', help)}` : message
            return answer(await clack.select<Value>({ message: question, options }))
        },
        async text(message, options = {}) {
            const validate = options.validate
            return answer(
                await clack.text({
                    message,
                    initialValue: options.initialValue,
                    validate: validate ? (value) => validate(value ?? '') : undefined,
                })
            )
        },
        async password(message, options = {}) {
            const validate = options.validate
            return answer(
                await clack.password({ message, validate: validate ? (value) => validate(value ?? '') : undefined })
            )
        },
        async confirm(message, options = {}) {
            return answer(await clack.confirm({ message, initialValue: options.initialValue ?? true }))
        },
        note(message, title) {
            clack.note(message, title)
        },
        spinner(message) {
            const spin = clack.spinner()
            spin.start(message)
            return { stop: (text) => spin.stop(text), error: (text) => spin.error(text) }
        },
    }
}
