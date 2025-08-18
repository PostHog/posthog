// Utility functions for parsing PostHog exception events

export interface ExceptionMetadata {
    uuid: string
    commitSha: string
    feature: string
    exceptionType: string
    exceptionValue: string
}

export interface StackTraceInfo {
    filename: string
    functionName: string
    lineNumber: string
}

export type ParsedExceptionData = string

/**
 * Extracts basic metadata from a PostHog exception event
 */
function extractExceptionMetadata(event: any): ExceptionMetadata {
    return {
        uuid: event?.uuid || 'Unknown',
        commitSha: event?.properties?.commit_sha || 'Unknown',
        feature: event?.properties?.feature || 'Unknown',
        exceptionType: event?.properties?.$exception_list?.[0]?.type || 'Unknown',
        exceptionValue: event?.properties?.$exception_list?.[0]?.value || 'Unknown',
    }
}

/**
 * Extracts stack trace information from exception frames
 */
function extractStackTraceInfo(event: any): StackTraceInfo {
    let filename = 'Unknown'
    let functionName = 'Unknown'
    let lineNumber = 'Unknown'

    const exceptionList = event?.properties?.$exception_list
    if (exceptionList && Array.isArray(exceptionList) && exceptionList[0]) {
        const exception = exceptionList[0]

        // Check if there's a stack trace in the exception
        if (exception.stacktrace && exception.stacktrace.frames) {
            const frames = exception.stacktrace.frames
            const appFrames = frames.filter((frame: any) => frame.in_app === true)
            const componentFrame = appFrames[appFrames.length - 1]
            if (componentFrame) {
                filename = componentFrame.filename || 'Unknown'
                functionName = componentFrame.function || 'Unknown'
                lineNumber = componentFrame.lineno || 'Unknown'
            }
        }
    }

    return { filename, functionName, lineNumber }
}

/**
 * Formats exception metadata and stack trace into a readable string
 */
function formatExceptionSummary(metadata: ExceptionMetadata, stackTrace: StackTraceInfo): string {
    return `UUID: ${metadata.uuid}
Commit SHA: ${metadata.commitSha}
Feature: ${metadata.feature}
Type: ${metadata.exceptionType}
Value: ${metadata.exceptionValue}
Filename: ${stackTrace.filename}
Function: ${stackTrace.functionName}
Line: ${stackTrace.lineNumber}`
}

/**
 * Main function to parse a PostHog exception event into a structured format
 */
export function parseExceptionEvent(event: any): ParsedExceptionData {
    const metadata = extractExceptionMetadata(event)
    const stackTrace = extractStackTraceInfo(event)
    const parsedData = formatExceptionSummary(metadata, stackTrace)

    return parsedData
}
