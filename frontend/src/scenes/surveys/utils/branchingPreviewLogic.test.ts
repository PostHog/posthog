import { SurveyQuestionBranchingType, SurveyQuestionType } from '~/types'

import { getNextQuestionIndex, getRatingScaleResponse } from './branchingPreviewLogic'

describe('getRatingScaleResponse', () => {
    describe('10-point NPS scale', () => {
        it('correctly identifies detractors (0-6)', () => {
            for (let i = 0; i <= 6; i++) {
                expect(getRatingScaleResponse(i, 10)).toBe('detractors')
            }
        })

        it('correctly identifies passives (7-8)', () => {
            for (let i = 7; i <= 8; i++) {
                expect(getRatingScaleResponse(i, 10)).toBe('passives')
            }
        })

        it('correctly identifies promoters (9-10)', () => {
            for (let i = 9; i <= 10; i++) {
                expect(getRatingScaleResponse(i, 10)).toBe('promoters')
            }
        })
    })

    describe('7-point scale', () => {
        it('correctly identifies negative responses (1-3)', () => {
            for (let i = 1; i <= 3; i++) {
                expect(getRatingScaleResponse(i, 7)).toBe('negative')
            }
        })

        it('correctly identifies neutral responses (4)', () => {
            expect(getRatingScaleResponse(4, 7)).toBe('neutral')
        })

        it('correctly identifies positive responses (5-7)', () => {
            for (let i = 5; i <= 7; i++) {
                expect(getRatingScaleResponse(i, 7)).toBe('positive')
            }
        })
    })

    describe('5-point scale', () => {
        it('correctly identifies negative responses (1-2)', () => {
            for (let i = 1; i <= 2; i++) {
                expect(getRatingScaleResponse(i, 5)).toBe('negative')
            }
        })

        it('correctly identifies neutral responses (3)', () => {
            expect(getRatingScaleResponse(3, 5)).toBe('neutral')
        })

        it('correctly identifies positive responses (4-5)', () => {
            for (let i = 4; i <= 5; i++) {
                expect(getRatingScaleResponse(i, 5)).toBe('positive')
            }
        })
    })
    it('returns neutral for unknown scales', () => {
        expect(getRatingScaleResponse(1, 4)).toBe('neutral')
    })
})

describe('getNextQuestionIndex', () => {
    const confirmationMessageIndex = 999
    const currentIndex = 1

    describe('basic branching types', () => {
        it('returns next question index when no branching is defined', () => {
            const question = {
                type: SurveyQuestionType.Rating as const,
                question: 'Test question',
                description: '',
                descriptionContentType: 'text' as const,
                display: 'number' as const,
                scale: 10,
                lowerBoundLabel: 'low',
                upperBoundLabel: 'high',
            }
            expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 5)).toBe(currentIndex + 1)
        })

        it('returns next question index for NextQuestion branching type', () => {
            const question = {
                type: SurveyQuestionType.Rating as const,
                question: 'Test question',
                description: '',
                descriptionContentType: 'text' as const,
                display: 'number' as const,
                scale: 10,
                lowerBoundLabel: 'low',
                upperBoundLabel: 'high',
                branching: { type: SurveyQuestionBranchingType.NextQuestion as const },
            }
            expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 5)).toBe(currentIndex + 1)
        })

        it('returns confirmation message index for End branching type', () => {
            const question = {
                type: SurveyQuestionType.Rating as const,
                question: 'Test question',
                description: '',
                descriptionContentType: 'text' as const,
                display: 'number' as const,
                scale: 10,
                lowerBoundLabel: 'low',
                upperBoundLabel: 'high',
                branching: { type: SurveyQuestionBranchingType.End as const },
            }
            expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 5)).toBe(
                confirmationMessageIndex
            )
        })

        it('returns specific question index for SpecificQuestion branching type', () => {
            const targetIndex = 5
            const question = {
                type: SurveyQuestionType.Rating as const,
                question: 'Test question',
                description: '',
                descriptionContentType: 'text' as const,
                display: 'number' as const,
                scale: 10,
                lowerBoundLabel: 'low',
                upperBoundLabel: 'high',
                branching: {
                    type: SurveyQuestionBranchingType.SpecificQuestion as const,
                    index: targetIndex,
                },
            }
            expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 5)).toBe(targetIndex)
        })
    })

    describe('response-based branching', () => {
        describe('rating questions', () => {
            it('handles rating question branching based on response', () => {
                const question = {
                    type: SurveyQuestionType.Rating as const,
                    question: 'Test question',
                    description: '',
                    descriptionContentType: 'text' as const,
                    display: 'number' as const,
                    scale: 10,
                    lowerBoundLabel: 'low',
                    upperBoundLabel: 'high',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased as const,
                        responseValues: {
                            detractors: 2,
                            passives: 3,
                            promoters: SurveyQuestionBranchingType.End,
                        },
                    },
                }
                // Test detractor response (0-6)
                expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 5)).toBe(2)
                // Test passive response (7-8)
                expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 7)).toBe(3)
                // Test promoter response (9-10)
                expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 9)).toBe(
                    confirmationMessageIndex
                )
            })
        })

        describe('single choice questions', () => {
            it('handles single choice question branching based on response', () => {
                const question = {
                    type: SurveyQuestionType.SingleChoice as const,
                    question: 'Test question',
                    description: '',
                    descriptionContentType: 'text' as const,
                    choices: ['Option A', 'Option B', 'Option C'],
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased as const,
                        responseValues: {
                            0: 2,
                            1: SurveyQuestionBranchingType.End,
                            2: 3,
                        },
                    },
                }
                // Test Option A response
                expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 'Option A')).toBe(2)
                // Test Option B response
                expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 'Option B')).toBe(
                    confirmationMessageIndex
                )
                // Test Option C response
                expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, 'Option C')).toBe(3)
            })
        })
    })

    describe('fallback behavior', () => {
        it('returns next question index for unsupported question types with response-based branching', () => {
            const question = {
                type: SurveyQuestionType.MultipleChoice as const,
                question: 'Test question',
                description: '',
                descriptionContentType: 'text' as const,
                choices: ['Option A', 'Option B', 'Option C'],
                branching: {
                    type: SurveyQuestionBranchingType.ResponseBased as const,
                    responseValues: {},
                },
            }
            expect(getNextQuestionIndex(question, confirmationMessageIndex, currentIndex, ['Option A'])).toBe(
                currentIndex + 1
            )
        })
    })
})
