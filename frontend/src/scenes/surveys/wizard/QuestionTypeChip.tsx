import { IconChevronDown, IconComment } from '@posthog/icons'
import { LemonDropdown } from '@posthog/lemon-ui'

import { IconAreaChart, IconGridView, IconLink, IconListView } from 'lib/lemon-ui/icons'

import { SurveyQuestionType } from '~/types'

import { SurveyQuestionLabel } from '../constants'

const QUESTION_TYPE_OPTIONS = [
    {
        type: SurveyQuestionType.Open,
        label: 'Open text',
        icon: <IconComment className="text-sm" />,
    },
    {
        type: SurveyQuestionType.Rating,
        label: 'Rating',
        icon: <IconAreaChart className="text-sm" />,
    },
    {
        type: SurveyQuestionType.SingleChoice,
        label: 'Single choice',
        icon: <IconListView className="text-sm" />,
    },
    {
        type: SurveyQuestionType.MultipleChoice,
        label: 'Multiple choice',
        icon: <IconGridView className="text-sm" />,
    },
    {
        type: SurveyQuestionType.Link,
        label: 'Link / Announcement',
        icon: <IconLink className="text-sm" />,
    },
]

function getIconForType(type: SurveyQuestionType): JSX.Element {
    const option = QUESTION_TYPE_OPTIONS.find((o) => o.type === type)
    return option?.icon || <IconComment className="text-sm" />
}

interface QuestionTypeChipProps {
    type: SurveyQuestionType
    onChange: (newType: SurveyQuestionType) => void
}

export function QuestionTypeChip({ type, onChange }: QuestionTypeChipProps): JSX.Element {
    return (
        <LemonDropdown
            overlay={
                <div className="p-1 space-y-0.5">
                    {QUESTION_TYPE_OPTIONS.map((option) => (
                        <button
                            key={option.type}
                            type="button"
                            onClick={() => onChange(option.type)}
                            className={`flex items-center gap-2 w-full px-2 py-1.5 text-left text-sm rounded hover:bg-fill-highlight-100 transition-colors ${
                                option.type === type ? 'bg-fill-highlight-100 font-medium' : ''
                            }`}
                        >
                            {option.icon}
                            <span>{option.label}</span>
                        </button>
                    ))}
                </div>
            }
            placement="bottom-start"
        >
            <button
                type="button"
                className="flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded border border-border bg-bg-light hover:border-border-bold hover:bg-fill-highlight-50 transition-colors cursor-pointer"
            >
                {getIconForType(type)}
                <span>{SurveyQuestionLabel[type]}</span>
                <IconChevronDown className="text-secondary text-xs" />
            </button>
        </LemonDropdown>
    )
}
