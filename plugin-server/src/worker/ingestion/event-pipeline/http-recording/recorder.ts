import { DestinationHttpRecording, HttpInteraction, HttpRecorder, HttpRecordingComparison } from './types'

export class DestinationHttpRecorder implements HttpRecorder {
    private currentRecording: DestinationHttpRecording | null = null

    public startRecording(eventUuid: string, teamId: number, destinationId: string): void {
        if (this.currentRecording) {
            throw new Error('Recording already in progress')
        }

        this.currentRecording = {
            metadata: {
                eventUuid,
                teamId,
                destinationId,
                timestamp: Date.now(),
            },
            interactions: [],
        }
    }

    public recordInteraction(interaction: HttpInteraction): void {
        if (!this.currentRecording) {
            throw new Error('No recording in progress')
        }
        this.currentRecording.interactions.push(interaction)
    }

    public stopRecording(): DestinationHttpRecording {
        if (!this.currentRecording) {
            throw new Error('No recording in progress')
        }
        const recording = this.currentRecording
        this.currentRecording = null
        return recording
    }

    public compareRecordings(
        oldRecording: DestinationHttpRecording,
        newRecording: DestinationHttpRecording
    ): HttpRecordingComparison {
        const differences: HttpRecordingComparison['differences'] = {
            missing: [],
            additional: [],
            different: [],
        }

        // Create maps for faster lookup of parent-child relationships
        const oldInteractionMap = new Map(oldRecording.interactions.map((i) => [i.id, i]))
        const newInteractionMap = new Map(newRecording.interactions.map((i) => [i.id, i]))

        // Check for missing interactions in new recording
        for (const oldInteraction of oldRecording.interactions) {
            if (!newInteractionMap.has(oldInteraction.id)) {
                differences.missing.push(oldInteraction)
                continue
            }

            const newInteraction = newInteractionMap.get(oldInteraction.id)!
            const interactionDifferences = this.compareInteractions(oldInteraction, newInteraction)

            if (interactionDifferences.length > 0) {
                differences.different.push({
                    old: oldInteraction,
                    new: newInteraction,
                    differences: interactionDifferences,
                })
            }
        }

        // Check for additional interactions in new recording
        for (const newInteraction of newRecording.interactions) {
            if (!oldInteractionMap.has(newInteraction.id)) {
                differences.additional.push(newInteraction)
            }
        }

        return {
            matches:
                differences.missing.length === 0 &&
                differences.additional.length === 0 &&
                differences.different.length === 0,
            differences:
                differences.missing.length === 0 &&
                differences.additional.length === 0 &&
                differences.different.length === 0
                    ? undefined
                    : differences,
        }
    }

    private compareInteractions(oldInteraction: HttpInteraction, newInteraction: HttpInteraction): string[] {
        const differences: string[] = []

        // Compare request fields
        if (oldInteraction.request.method !== newInteraction.request.method) {
            differences.push(`Method mismatch: ${oldInteraction.request.method} != ${newInteraction.request.method}`)
        }
        if (oldInteraction.request.url !== newInteraction.request.url) {
            differences.push(`URL mismatch: ${oldInteraction.request.url} != ${newInteraction.request.url}`)
        }
        if (JSON.stringify(oldInteraction.request.body) !== JSON.stringify(newInteraction.request.body)) {
            differences.push('Request body mismatch')
        }
        if (oldInteraction.request.parentRequestId !== newInteraction.request.parentRequestId) {
            differences.push(
                `Parent request ID mismatch: ${oldInteraction.request.parentRequestId} != ${newInteraction.request.parentRequestId}`
            )
        }

        // Compare response fields
        if (oldInteraction.response.status !== newInteraction.response.status) {
            differences.push(
                `Status code mismatch: ${oldInteraction.response.status} != ${newInteraction.response.status}`
            )
        }
        if (JSON.stringify(oldInteraction.response.body) !== JSON.stringify(newInteraction.response.body)) {
            differences.push('Response body mismatch')
        }

        // Compare headers (ignoring case)
        const oldRequestHeaders = this.normalizeHeaders(oldInteraction.request.headers)
        const newRequestHeaders = this.normalizeHeaders(newInteraction.request.headers)
        if (JSON.stringify(oldRequestHeaders) !== JSON.stringify(newRequestHeaders)) {
            differences.push('Request headers mismatch')
        }

        const oldResponseHeaders = this.normalizeHeaders(oldInteraction.response.headers)
        const newResponseHeaders = this.normalizeHeaders(newInteraction.response.headers)
        if (JSON.stringify(oldResponseHeaders) !== JSON.stringify(newResponseHeaders)) {
            differences.push('Response headers mismatch')
        }

        return differences
    }

    private normalizeHeaders(headers: Record<string, string>): Record<string, string> {
        return Object.entries(headers).reduce((acc, [key, value]) => {
            acc[key.toLowerCase()] = value
            return acc
        }, {} as Record<string, string>)
    }
}
