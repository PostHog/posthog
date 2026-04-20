import { Survey, SurveyQuestion, SurveyQuestionBranchingType } from '~/types'

import { getResponseConfiguration } from '../../components/question-branching/QuestionBranchingInput'
import { canQuestionHaveResponseBasedBranching } from '../../components/question-branching/utils'
import { NewSurvey } from '../../constants'
import type { EndNodeData, QuestionNodeData, SurveyFlowEdge, SurveyFlowNode, SurveyNodeHandle } from '../types'

const END_NODE_ID = 'end'

function getSourceHandles(question: SurveyQuestion, questionIndex: number): SurveyNodeHandle[] {
    const branching = question.branching

    if (
        branching?.type === SurveyQuestionBranchingType.ResponseBased &&
        canQuestionHaveResponseBasedBranching(question)
    ) {
        const responseConfig = getResponseConfiguration(question)
        return responseConfig.map((config) => ({
            id: `q${questionIndex}-response-${config.value}`,
            label: config.label,
        }))
    }

    return [{ id: `q${questionIndex}-next` }]
}

function getDestinationNodeId(
    branching: SurveyQuestion['branching'],
    questionIndex: number,
    totalQuestions: number
): string {
    if (!branching) {
        return questionIndex < totalQuestions - 1 ? `question-${questionIndex + 1}` : END_NODE_ID
    }

    switch (branching.type) {
        case SurveyQuestionBranchingType.NextQuestion:
            return questionIndex < totalQuestions - 1 ? `question-${questionIndex + 1}` : END_NODE_ID

        case SurveyQuestionBranchingType.End:
            return END_NODE_ID

        case SurveyQuestionBranchingType.SpecificQuestion:
            return `question-${branching.index}`

        case SurveyQuestionBranchingType.ResponseBased:
            return ''

        default:
            return questionIndex < totalQuestions - 1 ? `question-${questionIndex + 1}` : END_NODE_ID
    }
}

function getResponseDestinationNodeId(
    responseValue: string | number,
    responseValues: Record<string, unknown>,
    questionIndex: number,
    totalQuestions: number
): string {
    const destination = responseValues[String(responseValue)]

    if (!destination || destination === SurveyQuestionBranchingType.NextQuestion) {
        return questionIndex < totalQuestions - 1 ? `question-${questionIndex + 1}` : END_NODE_ID
    }

    if (destination === SurveyQuestionBranchingType.End) {
        return END_NODE_ID
    }

    if (typeof destination === 'number') {
        return `question-${destination}`
    }

    return questionIndex < totalQuestions - 1 ? `question-${questionIndex + 1}` : END_NODE_ID
}

function createEdgesForQuestion(
    question: SurveyQuestion,
    questionIndex: number,
    totalQuestions: number
): SurveyFlowEdge[] {
    const edges: SurveyFlowEdge[] = []
    const sourceNodeId = `question-${questionIndex}`
    const branching = question.branching

    if (
        branching?.type === SurveyQuestionBranchingType.ResponseBased &&
        canQuestionHaveResponseBasedBranching(question)
    ) {
        const responseConfig = getResponseConfiguration(question)
        const responseValues = branching.responseValues || {}

        for (const config of responseConfig) {
            const targetNodeId = getResponseDestinationNodeId(
                config.value,
                responseValues,
                questionIndex,
                totalQuestions
            )
            edges.push({
                id: `edge-q${questionIndex}-${config.value}`,
                source: sourceNodeId,
                target: targetNodeId,
                sourceHandle: `q${questionIndex}-response-${config.value}`,
                label: config.label,
            })
        }
    } else {
        const targetNodeId = getDestinationNodeId(branching, questionIndex, totalQuestions)
        edges.push({
            id: `edge-q${questionIndex}`,
            source: sourceNodeId,
            target: targetNodeId,
            sourceHandle: `q${questionIndex}-next`,
        })
    }

    return edges
}

export function surveyToGraph(survey: Survey | NewSurvey): {
    nodes: SurveyFlowNode[]
    edges: SurveyFlowEdge[]
} {
    const nodes: SurveyFlowNode[] = []
    const edges: SurveyFlowEdge[] = []

    survey.questions.forEach((question, index) => {
        const sourceHandles = getSourceHandles(question, index)

        const nodeData: QuestionNodeData = {
            survey,
            questionIndex: index,
            sourceHandles,
        }

        nodes.push({
            id: `question-${index}`,
            type: 'surveyQuestion',
            position: { x: 0, y: 0 },
            data: nodeData,
        })

        const questionEdges = createEdgesForQuestion(question, index, survey.questions.length)
        edges.push(...questionEdges)
    })

    const endNodeData: EndNodeData = {
        survey,
    }

    nodes.push({
        id: END_NODE_ID,
        type: 'end',
        position: { x: 0, y: 0 },
        data: endNodeData,
    })

    return { nodes, edges }
}
