import React from 'react'
import { addons, types } from '@storybook/addons'

import { ApiSelector } from './ApiSelector'
import { ADDON_ID } from './constants'

addons.register(ADDON_ID, () => {
    addons.add(ADDON_ID, {
        title: 'Api',
        type: types.TOOL,
        match: ({ viewMode }) => !!(viewMode && viewMode.match(/^(story|docs)$/)),
        render: () => <ApiSelector />,
    })
})
