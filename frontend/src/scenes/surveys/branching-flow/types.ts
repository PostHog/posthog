import type { Edge, Node } from '@xyflow/react'

import type { Survey } from '~/types'

import type { NewSurvey } from '../constants'

export interface SurveyNodeHandle {
    id: string
    label?: string
}

export interface QuestionNodeData extends Record<string, unknown> {
    survey: Survey | NewSurvey
    questionIndex: number
    sourceHandles: SurveyNodeHandle[]
}

export interface EndNodeData extends Record<string, unknown> {
    survey: Survey | NewSurvey
}

export type QuestionNode = Node<QuestionNodeData, 'surveyQuestion'>
export type EndNode = Node<EndNodeData, 'end'>

export type SurveyFlowNode = QuestionNode | EndNode

export interface SurveyFlowEdge extends Edge {
    label?: string
}
