import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { ExportsUnsubscribeModal } from './ExportsUnsubscribeModal'
import { exportsUnsubscribeModalLogic } from './exportsUnsubscribeModalLogic'

const meta: Meta<typeof ExportsUnsubscribeModal> = {
    title: 'Components/Exports Unsubscribe Modal',
}
export default meta

export const _ExportsUnsubscribeModal: StoryFn = () => {
    const { openModal } = useActions(exportsUnsubscribeModalLogic)

    useEffect(() => {
        openModal()
    })

    return <ExportsUnsubscribeModal />
}
