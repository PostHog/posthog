import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { ExportsUnsubscribeTable } from './ExportsUnsubscribeTable'
import { exportsUnsubscribeTableLogic } from './exportsUnsubscribeTableLogic'

const meta: Meta<typeof ExportsUnsubscribeTable> = {
    title: 'Components/Exports Unsubscribe Table',
}
export default meta

export const _ExportsUnsubscribeTable: StoryFn = () => {
    const { openModal } = useActions(exportsUnsubscribeTableLogic)

    useEffect(() => {
        openModal()
    })

    return <ExportsUnsubscribeTable />
}
