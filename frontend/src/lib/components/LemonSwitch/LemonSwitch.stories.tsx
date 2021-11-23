import React, { useState } from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonSwitch as _LemonSwitch } from './LemonSwitch'

export default {
    title: 'PostHog/Components/LemonSwitch',
    component: _LemonSwitch,
    parameters: { options: { showPanel: true } },
    argTypes: {
        loading: {
            control: {
                type: 'boolean',
            },
        },
    },
} as ComponentMeta<typeof _LemonSwitch>

export function LemonSwitch({ loading }: { loading: boolean }): JSX.Element {

    return <_LemonSwitch loading={loading} />
}
