import { connect, kea, key, path, props, selectors } from 'kea'
import {
    ErrorEventId,
    ErrorEventProperties,
    ErrorTrackingException,
    FingerprintRecordPart,
} from 'lib/components/Errors/types'
import {
    getAdditionalProperties,
    getExceptionAttributes,
    getExceptionList,
    getFingerprintRecords,
    getSessionId,
    hasStacktrace,
} from 'lib/components/Errors/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { errorPropertiesLogicType } from './errorPropertiesLogicType'
import { mightHaveRecording } from '../ViewRecordingButton/ViewRecordingButton'

export interface ErrorPropertiesLogicProps {
    properties?: ErrorEventProperties
    id: ErrorEventId
}

export const errorPropertiesLogic = kea<errorPropertiesLogicType>([
    path((key) => ['components', 'Errors', 'errorPropertiesLogic', key]),
    props({} as ErrorPropertiesLogicProps),
    key((props) => props.id),

    connect(() => ({
        values: [preflightLogic, ['isCloudOrDev']],
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
        sessionId: [
            (s) => [s.properties],
            (properties: ErrorEventProperties) => (properties ? getSessionId(properties) : undefined),
        ],
        mightHaveRecording: [
            (s) => [s.properties],
            (properties: ErrorEventProperties) => (properties ? mightHaveRecording(properties) : false),
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
    }),
])
