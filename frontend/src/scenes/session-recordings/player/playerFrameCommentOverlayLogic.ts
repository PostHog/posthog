import { actions, connect, kea, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { colonDelimitedDuration } from 'lib/utils'

import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationScope, AnnotationType } from '~/types'

import type { playerCommentOverlayLogicType } from './playerFrameCommentOverlayLogicType'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from './sessionRecordingPlayerLogic'

export interface RecordingAnnotationForm {
    // formatted time in recording, e.g. 00:00:00, 00:00:01, 00:00:02, etc.
    // this is a string because we want to be able to display the time in the recording
    timeInRecording: string | null
    // number of seconds into recording
    timestampInRecording?: number | null
    // the date that the timeInRecording represents
    dateForTimestamp?: Dayjs | null
    content: string
    scope: AnnotationScope
    recordingId: string | null
    annotationId: AnnotationType['id'] | null
}

export interface PlayerCommentOverlayLogicProps extends SessionRecordingPlayerLogicProps {
    recordingId: string
}

export const playerCommentOverlayLogic = kea<playerCommentOverlayLogicType>([
    path(['scenes', 'session-recordings', 'player', 'PlayerFrameAnnotationOverlay']),
    props({} as PlayerCommentOverlayLogicProps),
    connect((props: PlayerCommentOverlayLogicProps) => ({
        values: [sessionRecordingPlayerLogic(props), ['currentPlayerTime', 'currentTimestamp', 'sessionPlayerData']],
        actions: [
            annotationsModel,
            ['appendAnnotations', 'replaceAnnotation'],
            sessionRecordingPlayerLogic(props),
            ['setIsCommenting'],
        ],
    })),
    actions({
        editAnnotation: (annotation: RecordingAnnotationForm) => ({ annotation }),
    }),
    selectors({
        timestampUnits: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData) => {
                const endTimeSeconds = Math.floor(sessionPlayerData.durationMs / 1000)
                return endTimeSeconds > 3600 ? 3 : 2
            },
        ],
        formattedTimestamp: [
            (s) => [s.currentPlayerTime, s.timestampUnits],
            (currentPlayerTime, timestampUnits) => {
                return colonDelimitedDuration(currentPlayerTime / 1000, timestampUnits)
            },
        ],
    }),
    subscriptions(({ actions, values }) => ({
        formattedTimestamp: (formattedTimestamp) => {
            // as the timestamp from the player changes we track three representations of it
            actions.setRecordingAnnotationValue('timeInRecording', formattedTimestamp)
            actions.setRecordingAnnotationValue('timestampInRecording', values.currentPlayerTime)
            actions.setRecordingAnnotationValue('dateForTimestamp', dayjs(values.currentTimestamp))
        },
    })),
    listeners(({ actions }) => ({
        editAnnotation: ({ annotation }) => {
            actions.setRecordingAnnotationValue('content', annotation.content)
            actions.setRecordingAnnotationValue('scope', annotation.scope)
            actions.setRecordingAnnotationValue('recordingId', annotation.recordingId)
            actions.setRecordingAnnotationValue('annotationId', annotation.annotationId)
            // opening to edit also sets the player timestamp, which will update the timestamps in the form
            actions.setIsCommenting(true)
        },
    })),
    forms(({ props, values, actions }) => ({
        recordingAnnotation: {
            defaults: {
                timeInRecording: values.formattedTimestamp ?? '00:00:00',
                dateForTimestamp: null,
                content: '',
                scope: AnnotationScope.Recording,
                recordingId: null,
                annotationId: null,
            } as RecordingAnnotationForm,
            errors: ({ content, scope }) => ({
                content: !content?.trim()
                    ? 'An annotation must have text content.'
                    : content.length > 400
                    ? 'Must be 400 characters or less'
                    : null,
                scope: !scope
                    ? 'Scope is required.'
                    : [AnnotationScope.Recording, AnnotationScope.Project, AnnotationScope.Organization].includes(scope)
                    ? null
                    : 'Invalid scope.',
            }),
            submit: async (data) => {
                const { annotationId, content, scope, dateForTimestamp } = data

                if (!dateForTimestamp) {
                    throw new Error('Cannot comment without a timestamp.')
                }

                const apiPayload = {
                    date_marker: dateForTimestamp.toISOString(),
                    content,
                    scope,
                    recording_id: scope === AnnotationScope.Recording ? props.recordingId : null,
                }

                if (annotationId) {
                    const updatedAnnotation = await api.annotations.update(annotationId, apiPayload)
                    actions.replaceAnnotation(updatedAnnotation)
                } else {
                    const createdAnnotation = await api.annotations.create(apiPayload)
                    actions.appendAnnotations([createdAnnotation])
                }

                actions.resetRecordingAnnotation()
                actions.setIsCommenting(false)
            },
        },
    })),
])
