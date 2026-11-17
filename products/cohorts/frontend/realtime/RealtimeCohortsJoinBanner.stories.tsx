import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import type { RealtimeCohortsJoinStateEnumApi } from '../generated/api.schemas'
import { RealtimeCohortsJoinBanner } from './RealtimeCohortsJoinBanner'
import { realtimeCohortsJoinLogic } from './realtimeCohortsJoinLogic'

interface JoinBannerArgs {
    joinState: RealtimeCohortsJoinStateEnumApi
}

function JoinBannerInState({ joinState }: JoinBannerArgs): JSX.Element {
    const { setJoinState } = useActions(realtimeCohortsJoinLogic)
    useEffect(() => {
        setJoinState(joinState)
    }, [joinState, setJoinState])
    return <RealtimeCohortsJoinBanner />
}

const meta: Meta<JoinBannerArgs> = {
    title: 'Scenes-App/People/Cohorts/Realtime cohorts join banner',
    parameters: { testOptions: { snapshotBrowsers: [] } },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/realtime_cohorts/join/': { state: 'setting_up' } } })],
    render: (args) => <JoinBannerInState {...args} />,
}
export default meta

type Story = StoryObj<JoinBannerArgs>

export const SettingUp: Story = { args: { joinState: 'setting_up' } }

export const NotOpen: Story = { args: { joinState: 'not_open' } }

export const Refused: Story = { args: { joinState: 'refused' } }

export const Failed: Story = { args: { joinState: 'failed' } }
