import type { Decorator } from '@storybook/react'
import MockDate from 'mockdate'

declare module '@storybook/types' {
    interface Parameters {
        mockDate?: string | number | Date
    }
}

/** Global story decorator that allows mocking of dates.
 *
 * ```ts
 * export default {
 *   title: 'My story',
 *   component: MyComponent,
 *   parameters: {
 *     mockDate: '2023-02-01', // add mock date here
 *   },
 * } as ComponentMeta<typeof MyComponent>
 * ```
 */
export const withMockDate: Decorator = (Story, { parameters }) => {
    if (parameters.mockDate) {
        MockDate.set(parameters.mockDate)
    } else {
        MockDate.reset()
    }

    return <Story />
}
