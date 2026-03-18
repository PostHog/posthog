import { cloneElement } from 'react'

import { IconChevronDown, IconComment } from '@posthog/icons'
import { LemonDropdown } from '@posthog/lemon-ui'

import { SurveyQuestionType } from '~/types'

import { QUESTION_TYPE_OPTIONS, SurveyQuestionLabel } from '../constants'

function getIconForType(type: SurveyQuestionType): JSX.Element {
    const option = QUESTION_TYPE_OPTIONS.find((o) => o.type === type)
    const icon = option?.icon || <IconComment />
    return cloneElement(icon, { className: 'text-sm' })
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
                            {cloneElement(option.icon, { className: 'text-sm' })}
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
