import React from 'react'
import { Meta } from '@storybook/react'
import { FeatureFlag } from './FeatureFlag'
import { useMountedLogic } from 'kea'
import { personPropertiesModel } from '~/models/personPropertiesModel'

export default {
    title: 'Scenes/FeatureFlags',
    parameters: { options: { showPanel: false }, viewMode: 'canvas' }, // scene mode
} as Meta

export function NewFeatureFlag(): JSX.Element {
    useMountedLogic(personPropertiesModel)
    return <FeatureFlag />
}
