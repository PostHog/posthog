import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { PromptFlag, PromptPayload } from '~/types'
import { ModalPrompt, PopupPrompt, Prompt } from './Prompt'
import { promptLogic } from './promptLogic'
import BlankDashboardHog from 'public/blank-dashboard-hog.png'

export default {
    title: 'Components/Prompts',
    component: Prompt,
} as Meta

export function ModalPrompt_(): JSX.Element {
    // Ideally we'd instead mock the feature flag and payload but I couldn't get that to work
    const payload = {
        title: 'New hedgehog spotted!',
        body: "We have exciting news, there's a new hedge hog that has arrived!.",
        image: BlankDashboardHog,
        type: 'modal',
        primaryButtonText: 'Join the search!',
        primaryButtonURL: 'https://google.com',
    } as PromptPayload
    const openPromptFlag = {
        flag: 'new-hedgehog',
        payload: payload,
        showingPrompt: true,
    } as PromptFlag
    const { closePrompt } = useActions(promptLogic)

    return (
        <div className="bg-default p-4">
            <ModalPrompt openPromptFlag={openPromptFlag} payload={payload} closePrompt={closePrompt} inline />
        </div>
    )
}

export function PopupPrompt_(): JSX.Element {
    const payload = {
        title: 'New hedgehog spotted!',
        body: "We have exciting news, there's a new hedge hog that has arrived!.",
        image: BlankDashboardHog,
        type: 'popup',
        primaryButtonText: 'Join the search!',
        primaryButtonURL: 'https://google.com',
    } as PromptPayload
    const openPromptFlag = {
        flag: 'new-hedgehog',
        payload: payload,
        showingPrompt: true,
    } as PromptFlag
    const { closePrompt } = useActions(promptLogic)

    return (
        <div className="bg-default p-4">
            <PopupPrompt openPromptFlag={openPromptFlag} payload={payload} closePrompt={closePrompt} inline />
        </div>
    )
}
