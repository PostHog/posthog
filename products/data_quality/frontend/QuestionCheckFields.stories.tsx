import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { Form } from 'kea-forms'

import { mswDecorator } from '~/mocks/browser'

import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { CheckTypeEnumApi } from './generated/api.schemas'
import { QuestionCheckFields } from './QuestionCheckFields'

const preview = {
    inputs: [
        { input: 'A reading lamp for a desk', row_count: 3, probability: 0.94 },
        { input: 'item', row_count: 1, probability: 0.2 },
        { input: null, row_count: 1, probability: null },
    ],
    row_limit: 10,
    examined_row_count: 5,
    reused_decision_count: 1,
    new_decision_count: 1,
}

const meta: Meta<typeof QuestionCheckFields> = {
    title: 'Products/Data quality/Question check',
    component: QuestionCheckFields,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/data_quality_checks/check_types/': [
                    { check_type: 'question', description: '', requires_column: false, config_schema: {} },
                ],
                '/api/projects/:team_id/data_quality_checks/subjects/': [],
            },
            post: { '/api/projects/:team_id/data_quality_checks/question_preview/': preview },
        }),
    ],
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof meta>

export const Column: Story = {
    render: () => (
        <BindLogic logic={dataQualityCheckEditorLogic} props={{ surface: 'subject' }}>
            <Form logic={dataQualityCheckEditorLogic} formKey="checkForm">
                <QuestionCheckFields />
            </Form>
        </BindLogic>
    ),
    play: () => {
        const logic = dataQualityCheckEditorLogic({ surface: 'subject' })
        logic.actions.openEditor(null, { subjectType: 'table', subjectId: '00000000-0000-4000-8000-000000000001' }, [
            'description',
            'category',
        ])
        logic.actions.setCheckFormValues({
            checkType: CheckTypeEnumApi.Question,
            columnName: 'description',
            question: 'Does this description explain what the item is used for?',
            severity: 'warn',
        })
    },
}

export const SelectedRowFields: Story = {
    ...Column,
    play: async (context) => {
        await Column.play?.(context)
        dataQualityCheckEditorLogic({ surface: 'subject' }).actions.setCheckFormValues({
            questionInputMode: 'row',
            columnName: '',
            questionColumns: ['description', 'category'],
        })
    },
}

export const Preview: Story = {
    ...Column,
    // The preview request resolves after the play function returns, so the snapshot has to wait for
    // the result itself. Loader detection cannot stand in for it: the button spinner has not mounted yet.
    parameters: { testOptions: { waitForSelector: '[data-attr="data-quality-question-preview-summary"]' } },
    play: async (context) => {
        await Column.play?.(context)
        dataQualityCheckEditorLogic({ surface: 'subject' }).actions.requestQuestionPreview()
    },
}
