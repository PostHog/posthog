import { colonDelimitedDuration } from 'lib/utils/durations'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

const DEBUG_REPLAY_DISMISS_GROUP = 'session_recording_player'

// Trusted context must stay a build-time string: the session ID travels on the untrusted item below.
const DEBUG_REPLAY_INSTRUCTIONS_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: DEBUG_REPLAY_DISMISS_GROUP,
    value:
        "The user has a session recording open in the replay player. The session_recording item's key is the " +
        'session ID of that recording, and "this replay" or "this recording" means that session. When a ' +
        'session_recording_data item is present, it is JSON extracted from that recording: a timeline of page ' +
        'loads, console output, network requests and custom events, where t is seconds from the start of the ' +
        'recording. Read it first. DOM snapshots are counted in snapshot_counts but not included, and an omitted ' +
        'field means entries were left out for size. When a file whose name ends in -ph-recording.json is ' +
        'attached, it is the complete export of the recording, including every rrweb snapshot. It can be many ' +
        'megabytes, so query it with tools such as jq and do not print it whole. For anything else, load the ' +
        'investigating-replay skill and fetch the recording with session-recording-get. Do not ask the user for ' +
        'the session ID.',
}

export function buildDebugReplayDataContextItem(recordingDataJson: string): AttachedContextItem {
    return {
        type: 'session_recording_data',
        value: recordingDataJson,
        label: 'Recording data',
        dismissGroup: DEBUG_REPLAY_DISMISS_GROUP,
    }
}

export function buildDebugReplayContextItems(sessionRecordingId: string): AttachedContextItem[] {
    return [
        {
            type: 'session_recording',
            key: sessionRecordingId,
            label: 'Current session',
            dismissGroup: DEBUG_REPLAY_DISMISS_GROUP,
        },
        DEBUG_REPLAY_INSTRUCTIONS_CONTEXT_ITEM,
    ]
}

// The trusted instruction above identifies the attached export by this suffix.
export function debugReplayFileName(sessionRecordingId: string): string {
    return `export-${sessionRecordingId}-ph-recording.json`
}

export function buildDebugReplayPrompt(sessionRecordingId: string, playerTimeSeconds: number): string {
    return [
        'Debug this session replay.',
        '',
        `Session ID: ${sessionRecordingId}`,
        `I am ${colonDelimitedDuration(playerTimeSeconds, 2)} into the recording.`,
        '',
        'The recording JSON is attached. Use it to find what went wrong for the user in this session. ' +
            'Check exceptions, console errors, failed or slow ' +
            'network requests, rage clicks, and dead clicks. For each problem, tell me when it happens in the ' +
            'recording, the likely cause, and how to fix it. Start with whatever is closest to where I am now.',
    ].join('\n')
}
