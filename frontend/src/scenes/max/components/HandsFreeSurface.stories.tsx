import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { HandsFreeConnection, HandsFreeStatus, handsFreeLogic } from '../handsFreeLogic'
import { maxLogic } from '../maxLogic'
import { HandsFreeSurface } from './HandsFreeSurface'

const TAB_ID = 'hands-free-storybook'

interface DriverProps {
    status: HandsFreeStatus
    connection?: HandsFreeConnection
    partialTranscript?: string
    error?: string | null
}

// Mounts maxLogic + handsFreeLogic and drives them into a target state so each story
// captures a single visual configuration without spinning up real WebSockets or audio.
function HandsFreeSurfaceStory({ status, connection, partialTranscript, error }: DriverProps): JSX.Element {
    useMountedLogic(maxLogic({ panelId: TAB_ID }))
    const logic = handsFreeLogic({ panelId: TAB_ID })
    useMountedLogic(logic)
    const { setStatus, setConnection, setPartialTranscript, setError } = useActions(logic)

    useEffect(() => {
        setStatus(status)
        if (connection) {
            setConnection(connection)
        }
        if (partialTranscript) {
            setPartialTranscript(partialTranscript)
        }
        if (error) {
            setError(error)
        }
    }, [status, connection, partialTranscript, error, setStatus, setConnection, setPartialTranscript, setError])

    return (
        <div className="max-w-md mx-auto p-4 bg-bg-light border rounded">
            <HandsFreeSurface panelId={TAB_ID} />
        </div>
    )
}

const meta: Meta<typeof HandsFreeSurfaceStory> = {
    title: 'Scenes-App/PostHog AI/Hands-free surface',
    component: HandsFreeSurfaceStory,
    parameters: {
        layout: 'centered',
    },
}
export default meta

type Story = StoryObj<typeof HandsFreeSurfaceStory>

// Stories whose mic ring/pulse animates are excluded from visual regression — the
// running CSS animation makes the snapshot diff flake. Static visual states (speaking,
// error) keep their snapshot so we still catch unintended colour/layout drift.
const ANIMATED_SKIP_TAGS = ['test-skip']

export const Starting: Story = {
    args: { status: 'starting', connection: 'connecting' },
    tags: ANIMATED_SKIP_TAGS,
}

export const Listening: Story = {
    args: { status: 'listening', connection: 'connected' },
    tags: ANIMATED_SKIP_TAGS,
}

export const ListeningWithPartialTranscript: Story = {
    args: {
        status: 'listening',
        connection: 'connected',
        partialTranscript: 'how are the daily active users tracking against',
    },
    tags: ANIMATED_SKIP_TAGS,
}

export const Thinking: Story = {
    args: { status: 'thinking', connection: 'connected' },
    tags: ANIMATED_SKIP_TAGS,
}

export const Speaking: Story = {
    args: { status: 'speaking', connection: 'connected' },
}

export const Reconnecting: Story = {
    args: { status: 'listening', connection: 'reconnecting' },
    tags: ANIMATED_SKIP_TAGS,
}

export const WithError: Story = {
    args: {
        status: 'listening',
        connection: 'connected',
        error: 'Microphone access was denied.',
    },
}
