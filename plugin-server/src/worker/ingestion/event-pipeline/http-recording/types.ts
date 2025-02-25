export interface HttpInteraction {
    id: string
    timestamp: number
    request: {
        method: string
        url: string
        headers: Record<string, string>
        body?: any
        parentRequestId?: string
    }
    response: {
        status: number
        headers: Record<string, string>
        body?: any
        timing?: {
            duration?: number
        }
    }
}

export interface DestinationHttpRecording {
    metadata: {
        eventUuid: string
        teamId: number
        destinationId: string
        timestamp: number
    }
    interactions: HttpInteraction[]
}

export interface HttpRecordingComparison {
    matches: boolean
    differences?: {
        missing: HttpInteraction[]
        additional: HttpInteraction[]
        different: Array<{
            old: HttpInteraction
            new: HttpInteraction
            differences: string[]
        }>
    }
}

export interface HttpRecorder {
    startRecording(eventUuid: string, teamId: number, destinationId: string): void
    recordInteraction(interaction: HttpInteraction): void
    stopRecording(): DestinationHttpRecording
    compareRecordings(
        oldRecording: DestinationHttpRecording,
        newRecording: DestinationHttpRecording
    ): HttpRecordingComparison
}
