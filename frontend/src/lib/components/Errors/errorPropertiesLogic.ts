import { afterMount, connect, kea, key, path, props, selectors } from 'kea'

import {
    ErrorEventId,
    ErrorEventProperties,
    ErrorTrackingException,
    ErrorTrackingRelease,
    ErrorTrackingStackFrame,
    FingerprintRecordPart,
} from 'lib/components/Errors/types'
import {
    getAdditionalProperties,
    getExceptionAttributes,
    getExceptionList,
    getFingerprintRecords,
    getRecordingStatus,
    getSessionId,
    stacktraceHasInAppFrames,
} from 'lib/components/Errors/utils'
import { dayjs } from 'lib/dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { KeyedStackFrameRecords, stackFrameLogic } from './Frame/stackFrameLogic'
import type { errorPropertiesLogicType } from './errorPropertiesLogicType'

export interface ErrorPropertiesLogicProps {
    properties?: ErrorEventProperties
    id: ErrorEventId
}

export const errorPropertiesLogic = kea<errorPropertiesLogicType>([
    path((key) => ['components', 'Errors', 'errorPropertiesLogic', key]),
    props({} as ErrorPropertiesLogicProps),
    key((props) => props.id),

    connect(() => ({
        values: [preflightLogic, ['isCloudOrDev'], stackFrameLogic, ['stackFrameRecords', 'stackFrameRecordsLoading']],
        actions: [stackFrameLogic, ['loadFromRawIds']],
    })),

    selectors({
        properties: [
            () => [(_, props) => props.properties as ErrorEventProperties],
            (properties: ErrorEventProperties) => properties,
        ],
        exceptionAttributes: [
            (s) => [s.properties],
            (properties: ErrorEventProperties) => (properties ? getExceptionAttributes(properties) : null),
        ],
        exceptionList: [
            (s) => [s.properties],
            (properties: ErrorEventProperties) => {
                return properties ? getExceptionList(properties) : []
            },
        ],
        exceptionType: [
            (s) => [s.exceptionList],
            (excList: ErrorTrackingException[]) => {
                return excList[0]?.type || null
            },
        ],
        additionalProperties: [
            (s) => [s.properties, s.isCloudOrDev],
            (properties: ErrorEventProperties, isCloudOrDev: boolean | undefined) =>
                properties ? getAdditionalProperties(properties, isCloudOrDev) : {},
        ],
        fingerprintRecords: [
            (s) => [s.properties],
            (properties: ErrorEventProperties) => (properties ? getFingerprintRecords(properties) : []),
        ],
        hasStacktrace: [(s) => [s.exceptionList], (excList: ErrorTrackingException[]) => hasStacktrace(excList)],
        hasInAppFrames: [(s) => [s.exceptionList], (excList: ErrorTrackingException[]) => hasInAppFrames(excList)],
        sessionId: [
            (s) => [s.properties],
            (properties: ErrorEventProperties) => (properties ? getSessionId(properties) : undefined),
        ],
        recordingStatus: [
            (s) => [s.properties],
            (properties: ErrorEventProperties) => (properties ? getRecordingStatus(properties) : undefined),
        ],
        getExceptionFingerprint: [
            (s) => [s.fingerprintRecords],
            (records: FingerprintRecordPart[]) => (excId: string) =>
                records.find((record) => record.type === 'exception' && record.id === excId),
        ],
        getFrameFingerprint: [
            (s) => [s.fingerprintRecords],
            (records: FingerprintRecordPart[]) => (frameRawId: string) =>
                records.find((record) => record.type === 'frame' && record.raw_id === frameRawId),
        ],
        frames: [
            (s) => [s.exceptionList],
            (exceptionList: ErrorTrackingException[]) => {
                return exceptionList.flatMap((e) => e.stacktrace?.frames ?? []) as ErrorTrackingStackFrame[]
            },
        ],
        uuid: [(_, props) => [props.id], (id: ErrorEventId) => id],
        release: [
            (s) => [s.frames, s.stackFrameRecords],
            (frames: ErrorTrackingStackFrame[], stackFrameRecords: KeyedStackFrameRecords) => {
                if (!frames.length || Object.keys(stackFrameRecords).length === 0) {
                    return undefined
                }
                const rawIds = frames.map((f) => f.raw_id)
                const relatedReleases: ErrorTrackingRelease[] = rawIds
                    .map((id) => stackFrameRecords[id]?.release)
                    .filter((r) => !!r) as ErrorTrackingRelease[]

                const uniqueRelatedReleasesIds = [...new Set(relatedReleases.map((r) => r?.id))]
                if (uniqueRelatedReleasesIds.length === 1) {
                    return relatedReleases[0]
                }
                const kaboomFrame = frames[frames.length - 1]
                if (stackFrameRecords[kaboomFrame?.raw_id]?.release) {
                    return stackFrameRecords[kaboomFrame.raw_id].release
                }
                // get most recent release
                const sortedReleases = relatedReleases.sort(
                    (a, b) => dayjs(b.created_at).unix() - dayjs(a.created_at).unix()
                )
                return sortedReleases[0]
            },
        ],
    }),

    afterMount(({ values, actions }) => {
        const rawIds: string[] = values.exceptionList.flatMap((e) => e.stacktrace?.frames).map((frame) => frame.raw_id)
        actions.loadFromRawIds(rawIds)
    }),
])

function hasInAppFrames(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.some(({ stacktrace }) => stacktraceHasInAppFrames(stacktrace))
}

function hasStacktrace(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.length > 0 && exceptionList.some((e) => !!e.stacktrace)
}
