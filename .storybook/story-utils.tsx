import { ComponentMeta } from '@storybook/react'

export function componentStory<T extends (...args: any[]) => JSX.Element = () => JSX.Element>(
    meta: ComponentMeta<T>
): ComponentMeta<T> {
    return { ...meta, parameters: { ...meta.parameters, options: { ...meta?.parameters?.options, showPanel: true } } }
}
